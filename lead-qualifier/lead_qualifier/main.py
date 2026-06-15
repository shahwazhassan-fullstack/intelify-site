"""CLI entrypoint + orchestrator for the Lead Qualification Agent.

Pipeline per company:
  1. company research → 2. hiring signals → 3. qualify → 4. assemble (if qualified)

Run `python -m lead_qualifier.main --help` for usage.
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
from anthropic import Anthropic
from rich.console import Console
from rich.table import Table

from . import __version__
from .assemble import Assembler
from .company_research import CompanyResearcher
from .config import ConfigError, load_settings
from .hiring_signals import HiringResearcher
from .ingest import load_leads
from .job_history import get_history_provider
from .models import (
    Brief,
    CompanyRecord,
    CompanyRow,
    CompanySummary,
    HiringSignals,
    QualResult,
)
from .output import OutputWriter
from .qualify import Qualifier
from .utils.cache import Cache
from .utils.fetcher import Fetcher
from .utils.logger import setup_logging

app = typer.Typer(add_completion=False, help="Qualify B2B leads from company + hiring signals.")
console = Console()


# ──────────────────────────────────────────────────────────────────────────
# Per-company pipeline
# ──────────────────────────────────────────────────────────────────────────
class Pipeline:
    def __init__(self, settings, fetcher, client, offer_text, history, cache, draft_emails):
        self.settings = settings
        self.cache = cache
        self.draft_emails = draft_emails
        self.researcher = CompanyResearcher(settings, fetcher, client, cache)
        self.hiring = HiringResearcher(settings, fetcher, history, cache)
        self.qualifier = Qualifier(settings, client, offer_text, cache)
        self.assembler = Assembler(settings, client, offer_text, cache)
        self.log = logging.getLogger("lead_qualifier.pipeline")

    def process(self, row: CompanyRow) -> CompanyRecord:
        record = CompanyRecord(row=row)
        domain = row.domain

        # Resume from checkpoint if present.
        if self.cache:
            cp = self.cache.get_checkpoint(domain)
            if cp:
                self.log.info(f"[{domain}] resuming from checkpoint")
                return _record_from_checkpoint(row, cp)

        # Step 1 — company research
        try:
            record.summary = self.researcher.research(domain, row.company_name)
            if record.summary.error:
                record.errors.append(f"research: {record.summary.error}")
        except Exception as e:  # noqa: BLE001
            record.summary = CompanySummary(domain=domain, error=str(e))
            record.errors.append(f"research: {e}")

        # Step 2 — hiring signals
        try:
            record.hiring = self.hiring.research(domain)
            if record.hiring.error:
                record.errors.append(f"hiring: {record.hiring.error}")
        except Exception as e:  # noqa: BLE001
            record.hiring = HiringSignals(domain=domain, error=str(e))
            record.errors.append(f"hiring: {e}")

        # Step 3 — qualify
        try:
            record.qual = self.qualifier.qualify(record.summary, record.hiring)
            if record.qual.error:
                record.errors.append(f"qualify: {record.qual.error}")
        except Exception as e:  # noqa: BLE001
            record.qual = QualResult(domain=domain, error=str(e))
            record.errors.append(f"qualify: {e}")

        # Step 4 — assemble (qualified only)
        if record.qual and record.qual.qualified:
            try:
                record.brief = self.assembler.assemble(
                    record.summary, record.hiring, record.qual, row.company_name
                )
                if record.brief.error:
                    record.errors.append(f"assemble: {record.brief.error}")
            except Exception as e:  # noqa: BLE001
                record.brief = Brief(domain=domain, error=str(e))
                record.errors.append(f"assemble: {e}")

        if self.cache:
            self.cache.set_checkpoint(domain, _record_to_checkpoint(record))
        return record


# ──────────────────────────────────────────────────────────────────────────
# Checkpoint (de)serialisation
# ──────────────────────────────────────────────────────────────────────────
def _record_to_checkpoint(r: CompanyRecord) -> dict:
    return {
        "summary": asdict(r.summary) if r.summary else None,
        "hiring": asdict(r.hiring) if r.hiring else None,
        "qual": asdict(r.qual) if r.qual else None,
        "brief": asdict(r.brief) if r.brief else None,
        "errors": r.errors,
        "processed_at": r.processed_at,
    }


def _record_from_checkpoint(row: CompanyRow, cp: dict) -> CompanyRecord:
    from .models import JobOpening

    summary = CompanySummary(**cp["summary"]) if cp.get("summary") else None
    hiring = None
    if cp.get("hiring"):
        h = dict(cp["hiring"])
        h["openings"] = [JobOpening(**o) for o in h.get("openings", [])]
        hiring = HiringSignals(**h)
    qual = QualResult(**cp["qual"]) if cp.get("qual") else None
    brief = Brief(**cp["brief"]) if cp.get("brief") else None
    return CompanyRecord(
        row=row, summary=summary, hiring=hiring, qual=qual, brief=brief,
        errors=cp.get("errors", []), processed_at=cp.get("processed_at", ""),
    )


# ──────────────────────────────────────────────────────────────────────────
# Validate (dry-run) mode
# ──────────────────────────────────────────────────────────────────────────
def _validate(input_file: Path, offer_file: Path, env_file: Optional[Path]) -> int:
    console.rule("[bold]Validation (dry-run) — no API credits will be spent")
    ok = True

    # 1. Secrets / config
    try:
        settings = load_settings(env_file, validate_keys=True)
        console.print(f"[green]✓[/green] ANTHROPIC_API_KEY present; model = {settings.model}")
        console.print(f"[green]✓[/green] score threshold = {settings.score_threshold}")
    except ConfigError as e:
        console.print(f"[red]✗[/red] {e}")
        ok = False

    # 2. Offer file
    if offer_file.exists() and offer_file.read_text(encoding="utf-8").strip():
        console.print(f"[green]✓[/green] offer file readable: {offer_file}")
    else:
        console.print(f"[red]✗[/red] offer file missing or empty: {offer_file}")
        ok = False

    # 3. Leads file
    try:
        report = load_leads(input_file)
        console.print(
            f"[green]✓[/green] leads file parsed: {len(report.rows)} valid row(s), "
            f"{len(report.skipped)} skipped; domain column = '{report.domain_column}'"
        )
        if report.rows[:3]:
            console.print("  sample domains: " + ", ".join(r.domain for r in report.rows[:3]))
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]✗[/red] leads file problem: {e}")
        ok = False

    console.rule()
    if ok:
        console.print("[bold green]Validation passed.[/bold green] Re-run without --validate to process.")
        return 0
    console.print("[bold red]Validation failed.[/bold red] Fix the issues above.")
    return 1


# ──────────────────────────────────────────────────────────────────────────
# Main command
# ──────────────────────────────────────────────────────────────────────────
@app.command()
def run(
    input_file: Path = typer.Option(..., "--input", "-i", help="Leads file (CSV or XLSX)."),
    offer_file: Path = typer.Option(..., "--offer", "-o", help="Markdown/text file describing what you sell."),
    output_dir: Path = typer.Option(Path("output"), "--output-dir", help="Output directory."),
    threshold: Optional[int] = typer.Option(None, "--threshold", "-t", help="Qualify score threshold (1-10). Overrides .env."),
    draft_emails: bool = typer.Option(True, "--draft-emails/--no-draft-emails", help="Draft AIDA cold emails for qualified leads (on by default)."),
    history_provider: str = typer.Option("none", "--history-provider", help="'none' (free snapshots) or 'api' (paid history)."),
    limit: Optional[int] = typer.Option(None, "--limit", help="Process only the first N leads (for testing)."),
    workers: Optional[int] = typer.Option(None, "--workers", help="Parallel workers. Overrides .env MAX_WORKERS."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable cache + checkpoints (re-fetch and re-call everything)."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Path to .env (default: auto-discover)."),
    validate: bool = typer.Option(False, "--validate", help="Dry-run: check inputs + keys without spending API credits."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose console logging."),
):
    """Research, qualify, and write briefs for a list of company leads."""
    setup_logging(output_dir, level=logging.DEBUG if verbose else logging.INFO)
    log = logging.getLogger("lead_qualifier.main")
    console.print(f"[bold cyan]Lead Qualifier v{__version__}[/bold cyan]")

    if validate:
        raise typer.Exit(_validate(input_file, offer_file, env_file))

    # ── Load config + inputs ──
    try:
        settings = load_settings(env_file, validate_keys=True)
    except ConfigError as e:
        console.print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(1)

    if threshold is not None:
        settings.score_threshold = max(1, min(10, threshold))
    if workers is not None:
        settings.max_workers = max(1, workers)

    if not offer_file.exists() or not offer_file.read_text(encoding="utf-8").strip():
        console.print(f"[red]Offer file missing or empty:[/red] {offer_file}")
        raise typer.Exit(1)
    offer_text = offer_file.read_text(encoding="utf-8").strip()

    try:
        report = load_leads(input_file, limit=limit)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Input error:[/red] {e}")
        raise typer.Exit(1)
    if not report.ok:
        console.print("[red]No valid leads to process.[/red]")
        raise typer.Exit(1)

    # ── Wire up shared services ──
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = None if no_cache else Cache(output_dir / "cache.db")
    fetcher = Fetcher(settings.user_agent, delay=settings.request_delay, cache=cache)
    client = Anthropic(api_key=settings.anthropic_api_key)
    try:
        history = get_history_provider(history_provider, settings, snapshots_db=output_dir / "snapshots.db")
    except ConfigError as e:
        console.print(f"[red]History provider error:[/red] {e}")
        raise typer.Exit(1)

    pipeline = Pipeline(settings, fetcher, client, offer_text, history, cache, draft_emails)
    writer = OutputWriter(output_dir)

    console.print(
        f"Processing [bold]{len(report.rows)}[/bold] companies "
        f"(threshold ≥ {settings.score_threshold}, history={history_provider}, "
        f"workers={settings.max_workers})\n"
    )

    # ── Process (parallel, but progress printed as each completes) ──
    records: list[CompanyRecord] = []
    total = len(report.rows)
    done = 0

    def _run_one(row: CompanyRow) -> CompanyRecord:
        return pipeline.process(row)

    with ThreadPoolExecutor(max_workers=settings.max_workers) as ex:
        futures = {ex.submit(_run_one, row): row for row in report.rows}
        for fut in as_completed(futures):
            row = futures[fut]
            done += 1
            try:
                rec = fut.result()
            except Exception as e:  # noqa: BLE001 — never let one company kill the run
                log.exception(f"[{row.domain}] fatal pipeline error")
                rec = CompanyRecord(row=row, errors=[f"fatal: {e}"])
            records.append(rec)
            _print_progress(done, total, rec)
            if rec.qual and rec.qual.qualified:
                writer.write_brief(rec)

    # ── Outputs ──
    console.print()
    paths = writer.write_spreadsheets(records)
    writer.write_summary(records, meta={
        "input_file": str(input_file),
        "offer_file": str(offer_file),
        "model": settings.model,
        "threshold": settings.score_threshold,
        "history_provider": history_provider,
        "skipped_rows": len(report.skipped),
    })

    if cache:
        cache.close()

    _print_final_table(records, paths)


def _print_progress(done: int, total: int, rec: CompanyRecord) -> None:
    if rec.qual and rec.qual.qualified:
        tag = f"[bold green]QUALIFIED {rec.qual.score}/10[/bold green]"
    elif rec.qual:
        tag = f"[yellow]disqualified {rec.qual.score}/10[/yellow]"
    else:
        tag = "[red]error[/red]"
    openings = rec.hiring.total_open if rec.hiring else 0
    console.print(f"[dim]({done}/{total})[/dim] {rec.domain:<32} {tag}  · {openings} openings")


def _print_final_table(records: list[CompanyRecord], paths: dict) -> None:
    q = sum(1 for r in records if r.qual and r.qual.qualified)
    d = sum(1 for r in records if r.qual and not r.qual.qualified)
    e = sum(1 for r in records if r.errors)
    nc = sum(1 for r in records if r.hiring and not r.hiring.found_careers)

    table = Table(title="Run Complete", show_header=False)
    table.add_row("Qualified", f"[green]{q}[/green]")
    table.add_row("Disqualified", f"[yellow]{d}[/yellow]")
    table.add_row("With errors", f"[red]{e}[/red]")
    table.add_row("No careers page", str(nc))
    table.add_row("Qualified CSV", paths["qualified"])
    table.add_row("Unqualified CSV", paths["unqualified"])
    table.add_row("Briefs", "output/briefs/")
    console.print(table)


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Progress is checkpointed — re-run to resume.[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()

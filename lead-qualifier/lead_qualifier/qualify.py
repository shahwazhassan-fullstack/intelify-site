"""Step 3 — qualification.

Evaluate fit between {company summary + hiring signals} and the user's offer
description using Claude. Returns a 1–10 fit score, qualify/disqualify against
the configured threshold, and a rationale that explicitly references the hiring
signals.
"""

from __future__ import annotations

import json

from anthropic import Anthropic

from .company_research import _extract_json, response_text
from .config import Settings, load_prompt
from .models import CompanySummary, HiringSignals, QualResult
from .utils.cache import Cache, make_key
from .utils.logger import get_logger

log = get_logger("qualify")


class Qualifier:
    def __init__(self, settings: Settings, client: Anthropic, offer_text: str, cache: Cache | None = None):
        self.settings = settings
        self.client = client
        self.offer_text = offer_text
        self.cache = cache
        self.prompt_template = load_prompt("qualify")

    def qualify(self, summary: CompanySummary, hiring: HiringSignals) -> QualResult:
        domain = summary.domain
        # Cache key includes offer text + model so changing the offer re-evaluates.
        cache_key = make_key(
            "qualify", domain, self.settings.model, self.offer_text,
            summary.summary, hiring.total_open, sorted(hiring.by_function.items()),
        )
        if self.cache:
            cached = self.cache.get("qualify", cache_key)
            if cached:
                log.info(f"[{domain}] qualification from cache")
                return QualResult(**cached)

        prompt = self.prompt_template.format(
            offer=self.offer_text,
            threshold=self.settings.score_threshold,
            company_summary=_render_summary(summary),
            hiring_signals=_render_hiring(hiring),
        )

        try:
            resp = self.client.messages.create(
                model=self.settings.model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            data = _extract_json(response_text(resp))
        except Exception as e:  # noqa: BLE001
            log.warning(f"[{domain}] qualification failed: {e}")
            return QualResult(domain=domain, error=f"qualification failed: {e}")

        score = _coerce_score(data.get("score"))
        qualified = score >= self.settings.score_threshold
        result = QualResult(
            domain=domain,
            score=score,
            qualified=qualified,
            rationale=data.get("rationale", "").strip(),
        )
        if self.cache:
            from dataclasses import asdict
            self.cache.set("qualify", cache_key, asdict(result))
        return result


def _coerce_score(raw) -> int:
    try:
        val = int(round(float(raw)))
    except (TypeError, ValueError):
        return 0
    return max(1, min(10, val))


def _render_summary(s: CompanySummary) -> str:
    if s.error:
        return f"(company research had an error: {s.error})"
    parts = [
        f"Summary: {s.summary}",
        f"Industry: {s.industry}",
        f"Products/Services: {', '.join(s.products_services) if s.products_services else 'n/a'}",
        f"Size/Stage signals: {s.size_stage_signals or 'n/a'}",
    ]
    return "\n".join(parts)


def _render_hiring(h: HiringSignals) -> str:
    if not h.found_careers:
        return "No careers page found; no current hiring signals available."
    lines = [
        f"Careers page: {h.careers_url}",
        f"ATS: {h.ats or 'unknown'}",
        f"Total current open roles: {h.total_open}",
        "Open roles by function: " + (
            ", ".join(f"{fn} ({n})" for fn, n in h.by_function.items()) or "none"
        ),
        f"Hiring momentum: {h.history_summary} (trend: {h.trend})",
    ]
    if h.openings:
        lines.append("Sample roles:")
        for o in h.openings[:15]:
            loc = f" — {o.location}" if o.location else ""
            lines.append(f"  • {o.title} [{o.function}/{o.seniority}]{loc}")
    return "\n".join(lines)

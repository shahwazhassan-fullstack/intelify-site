"""Step 1 — company research.

Fetch the homepage plus discoverable key pages (/about, /products, /services,
/pricing, …), then summarise what the company does using Claude.
"""

from __future__ import annotations

import json
from urllib.parse import urljoin

from .config import Settings, load_prompt
from .llm import LLMClient
from .models import CompanySummary
from .utils.cache import Cache, make_key
from .utils.fetcher import Fetcher
from .utils.logger import get_logger

log = get_logger("company_research")

# Key pages we try directly, plus keywords for link discovery.
KEY_PATHS = ["/about", "/about-us", "/company", "/products", "/product",
             "/services", "/solutions", "/pricing", "/platform", "/what-we-do"]
LINK_KEYWORDS = ["about", "product", "service", "solution", "pricing",
                 "platform", "company", "what we do"]

MAX_PAGES = 5
PER_PAGE_CHARS = 6000


class CompanyResearcher:
    def __init__(self, settings: Settings, fetcher: Fetcher, client: LLMClient, cache: Cache | None = None):
        self.settings = settings
        self.fetcher = fetcher
        self.client = client
        self.cache = cache
        self.prompt_template = load_prompt("company_summary")

    def research(self, domain: str, company_name: str | None = None) -> CompanySummary:
        cache_key = make_key("company_summary", domain, self.settings.model)
        if self.cache:
            cached = self.cache.get("company_summary", cache_key)
            if cached:
                log.info(f"[{domain}] company summary from cache")
                return CompanySummary(**cached)

        pages = self._collect_pages(domain)
        if not pages:
            return CompanySummary(domain=domain, error="Could not fetch any company pages")

        corpus = "\n\n".join(
            f"--- PAGE: {url} ---\n{text[:PER_PAGE_CHARS]}" for url, text in pages.items()
        )
        summary = self._summarize(domain, company_name, corpus, list(pages.keys()))

        if self.cache and not summary.error:
            from dataclasses import asdict
            self.cache.set("company_summary", cache_key, asdict(summary))
        return summary

    def _collect_pages(self, domain: str) -> dict[str, str]:
        """Fetch homepage + a handful of relevant internal pages → {url: text}."""
        pages: dict[str, str] = {}
        home = self.fetcher.fetch(f"https://{domain}")
        if not home.ok:
            # try http / www variants
            for alt in (f"http://{domain}", f"https://www.{domain}"):
                home = self.fetcher.fetch(alt)
                if home.ok:
                    break
        if not home.ok:
            log.warning(f"[{domain}] homepage fetch failed (status {home.status})")
            return pages

        pages[home.final_url] = home.text(PER_PAGE_CHARS)

        # Candidate internal links: discovered + common paths.
        candidates: list[str] = self.fetcher.discover_links(home, LINK_KEYWORDS)
        for path in KEY_PATHS:
            candidates.append(urljoin(home.final_url, path))

        # De-dupe, keep same host, cap count.
        from urllib.parse import urlparse
        host = urlparse(home.final_url).netloc
        seen = {home.final_url.rstrip("/")}
        for url in candidates:
            if len(pages) >= MAX_PAGES:
                break
            u = url.rstrip("/")
            if u in seen or urlparse(url).netloc != host:
                continue
            seen.add(u)
            res = self.fetcher.fetch(url)
            if res.ok and len(res.text(500)) > 200:
                pages[res.final_url] = res.text(PER_PAGE_CHARS)
        log.info(f"[{domain}] read {len(pages)} page(s) for company research")
        return pages

    def _summarize(self, domain, company_name, corpus, pages_read) -> CompanySummary:
        prompt = self.prompt_template.format(
            domain=domain,
            company_name=company_name or "(unknown)",
            corpus=corpus,
        )
        try:
            text = self.client.complete(prompt, max_tokens=2000)
            data = _extract_json(text)
        except Exception as e:  # noqa: BLE001
            log.warning(f"[{domain}] summarization failed: {e}")
            return CompanySummary(domain=domain, pages_read=pages_read,
                                  error=f"summarization failed: {e}")

        return CompanySummary(
            domain=domain,
            summary=data.get("summary", ""),
            industry=data.get("industry", ""),
            products_services=data.get("products_services", []) or [],
            size_stage_signals=data.get("size_stage_signals", ""),
            pages_read=pages_read,
        )


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}

"""Step 2 — hiring-signal research.

Find the careers page, detect the ATS, pull current openings (API preferred,
HTML scrape fallback), normalise + group by function, and attach a ~6-month
history summary via the pluggable history provider.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from .ats import ATSRegistry
from .ats.scraper import scrape_careers_html
from .config import Settings
from .job_history.base import JobHistoryProvider
from .models import HiringSignals, JobOpening
from .utils.cache import Cache, make_key
from .utils.fetcher import Fetcher
from .utils.logger import get_logger

log = get_logger("hiring_signals")

CAREERS_PATHS = ["/careers", "/career", "/jobs", "/join", "/join-us", "/work-with-us",
                 "/company/careers", "/about/careers", "/we-are-hiring", "/hiring",
                 "/about/jobs", "/team/careers"]
CAREERS_KEYWORDS = ["career", "job", "join us", "join our team", "we're hiring",
                    "we are hiring", "open position", "open role", "vacanc", "work with us"]


class HiringResearcher:
    def __init__(
        self,
        settings: Settings,
        fetcher: Fetcher,
        history: JobHistoryProvider,
        cache: Cache | None = None,
    ):
        self.settings = settings
        self.fetcher = fetcher
        self.history = history
        self.cache = cache
        self.registry = ATSRegistry(fetcher)

    def research(self, domain: str) -> HiringSignals:
        cache_key = make_key("hiring", domain)
        if self.cache:
            cached = self.cache.get("hiring", cache_key, max_age=60 * 60 * 24)
            if cached:
                log.info(f"[{domain}] hiring signals from cache")
                sig = _signals_from_dict(cached)
                # History still needs recording for the snapshot ledger trend.
                hist = self.history.record_and_summarize(domain, sig.openings)
                sig.history_summary, sig.trend = hist.summary, hist.trend
                return sig

        careers_url, careers_html = self._find_careers(domain)
        sig = HiringSignals(domain=domain, careers_url=careers_url)

        if not careers_url:
            sig.error = "No careers page found"
            log.warning(f"[{domain}] no careers page found")
            hist = self.history.record_and_summarize(domain, [])
            sig.history_summary, sig.trend = hist.summary, hist.trend
            return sig

        # Detect ATS from the careers URL + its HTML, and from homepage links.
        provider, token = self.registry.detect(careers_url, careers_html, domain)
        openings: list[JobOpening] = []
        if provider and token:
            sig.ats = provider.name
            openings = provider.fetch_openings(token)
            log.info(f"[{domain}] {provider.name} returned {len(openings)} opening(s)")

        # Fallback: scrape the careers HTML if no ATS or ATS returned nothing.
        if not openings:
            res = self.fetcher.fetch(careers_url)
            if res.ok:
                openings = scrape_careers_html(self.fetcher, res)
                if openings:
                    sig.ats = sig.ats or "html-scrape"

        sig.openings = openings
        sig.total_open = len(openings)
        sig.by_function = _group_by_function(openings)

        hist = self.history.record_and_summarize(domain, openings)
        sig.history_summary, sig.trend = hist.summary, hist.trend

        if self.cache:
            self.cache.set("hiring", cache_key, _signals_to_dict(sig))
        return sig

    def _find_careers(self, domain: str) -> tuple[str | None, str | None]:
        """Return (careers_url, html) or (None, None)."""
        home = self.fetcher.fetch(f"https://{domain}")
        if not home.ok:
            for alt in (f"http://{domain}", f"https://www.{domain}"):
                home = self.fetcher.fetch(alt)
                if home.ok:
                    break

        # 1. Links discovered on the homepage.
        if home.ok:
            for link in self.fetcher.discover_links(home, CAREERS_KEYWORDS):
                res = self.fetcher.fetch(link)
                if res.ok and self._looks_like_careers(res.text(2000), link):
                    return res.final_url, res.html

        # 2. Common direct paths.
        base = home.final_url if home.ok else f"https://{domain}"
        for path in CAREERS_PATHS:
            url = urljoin(base, path)
            res = self.fetcher.fetch(url)
            if res.ok and self._looks_like_careers(res.text(2000), url):
                return res.final_url, res.html

        return None, None

    @staticmethod
    def _looks_like_careers(text: str, url: str) -> bool:
        hay = f"{url.lower()} {text.lower()}"
        signals = ["job", "career", "position", "opening", "role", "hiring",
                   "join our team", "apply", "vacanc"]
        return sum(s in hay for s in signals) >= 2


def _group_by_function(openings: list[JobOpening]) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in openings:
        out[o.function] = out.get(o.function, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


# ── (de)serialisation for cache ──────────────────────────────────────────────
def _signals_to_dict(sig: HiringSignals) -> dict:
    from dataclasses import asdict
    return asdict(sig)


def _signals_from_dict(d: dict) -> HiringSignals:
    openings = [JobOpening(**o) for o in d.get("openings", [])]
    return HiringSignals(
        domain=d["domain"],
        careers_url=d.get("careers_url"),
        ats=d.get("ats"),
        openings=openings,
        by_function=d.get("by_function", {}),
        total_open=d.get("total_open", 0),
        history_summary=d.get("history_summary", ""),
        trend=d.get("trend", "unknown"),
        error=d.get("error"),
    )

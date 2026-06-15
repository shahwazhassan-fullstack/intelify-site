"""Polite web fetching: requests first, Playwright fallback for JS-heavy sites.

Features:
  * robots.txt awareness (cached per host)
  * real, identifiable User-Agent
  * polite per-host delays
  * retries with exponential backoff (tenacity)
  * automatic detection of "thin" HTML (likely client-rendered) → Playwright
  * optional HTTP-response caching via the shared Cache
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .cache import Cache, make_key
from .logger import get_logger

log = get_logger("fetcher")


@dataclass
class FetchResult:
    url: str
    status: int
    html: str
    final_url: str
    used_browser: bool = False
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and bool(self.html)

    def soup(self) -> BeautifulSoup:
        return BeautifulSoup(self.html, "lxml")

    def text(self, max_chars: int = 20000) -> str:
        """Visible text content, whitespace-collapsed, truncated."""
        soup = self.soup()
        for tag in soup(["script", "style", "noscript", "svg", "header", "footer"]):
            tag.decompose()
        txt = " ".join(soup.get_text(separator=" ").split())
        return txt[:max_chars]


class Fetcher:
    """Shared, thread-safe fetcher with per-host rate limiting."""

    def __init__(
        self,
        user_agent: str,
        *,
        delay: float = 1.0,
        cache: Optional[Cache] = None,
        respect_robots: bool = True,
        timeout: int = 20,
    ):
        self.user_agent = user_agent
        self.delay = delay
        self.cache = cache
        self.respect_robots = respect_robots
        self.timeout = timeout

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self._last_hit: dict[str, float] = {}
        self._lock = threading.Lock()
        self._playwright = None  # lazy

    # ── robots.txt ───────────────────────────────────────────────────────────
    def _can_fetch(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        host = urlparse(url).netloc
        with self._lock:
            rp = self._robots.get(host, "missing")
        if rp == "missing":
            rp = self._load_robots(url, host)
        if rp is None:
            return True  # no robots.txt → allowed
        return rp.can_fetch(self.user_agent, url)

    def _load_robots(self, url: str, host: str) -> Optional[RobotFileParser]:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        rp = RobotFileParser()
        try:
            resp = self._session.get(robots_url, timeout=self.timeout)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp = None
        except requests.RequestException:
            rp = None
        with self._lock:
            self._robots[host] = rp
        return rp

    # ── rate limiting ─────────────────────────────────────────────────────────
    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._lock:
            last = self._last_hit.get(host, 0.0)
            wait = self.delay - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        with self._lock:
            self._last_hit[host] = time.time()

    # ── core fetch ─────────────────────────────────────────────────────────────
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=16),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def _http_get(self, url: str) -> requests.Response:
        return self._session.get(url, timeout=self.timeout, allow_redirects=True)

    def fetch(self, url: str, *, allow_browser: bool = True, use_cache: bool = True) -> FetchResult:
        """Fetch a URL, returning a FetchResult. Never raises for HTTP errors."""
        cache_key = make_key("fetch", url)
        if use_cache and self.cache:
            cached = self.cache.get("fetch", cache_key, max_age=60 * 60 * 24 * 7)
            if cached:
                return FetchResult(**{**cached, "from_cache": True})

        if not self._can_fetch(url):
            log.info(f"robots.txt disallows fetching {url}")
            return FetchResult(url=url, status=999, html="", final_url=url)

        self._throttle(url)
        try:
            resp = self._http_get(url)
            html = resp.text or ""
            result = FetchResult(
                url=url, status=resp.status_code, html=html, final_url=resp.url
            )
        except requests.RequestException as e:
            log.warning(f"requests failed for {url}: {e}")
            result = FetchResult(url=url, status=0, html="", final_url=url)

        # Fall back to a headless browser when the page looks client-rendered.
        if allow_browser and self._looks_thin(result):
            log.info(f"thin/empty HTML for {url} → trying headless browser")
            browser_html = self._browser_get(url)
            if browser_html:
                result = FetchResult(
                    url=url, status=200, html=browser_html,
                    final_url=url, used_browser=True,
                )

        if use_cache and self.cache and result.ok:
            self.cache.set("fetch", cache_key, {
                "url": result.url, "status": result.status, "html": result.html,
                "final_url": result.final_url, "used_browser": result.used_browser,
            })
        return result

    @staticmethod
    def _looks_thin(result: FetchResult) -> bool:
        """Heuristic: empty body, or very little text relative to markup → JS app."""
        if not result.html:
            return True
        soup = BeautifulSoup(result.html, "lxml")
        body = soup.body
        if body is None:
            return True
        text = " ".join(body.get_text(separator=" ").split())
        # Classic SPA shells: lots of <script>, tiny visible text.
        if len(text) < 200 and len(soup.find_all("script")) >= 1:
            return True
        return False

    # ── Playwright fallback ──────────────────────────────────────────────────
    def _browser_get(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright  # noqa: WPS433
        except ImportError:
            log.warning("Playwright not installed; cannot render JS site. "
                        "Run: pip install playwright && playwright install chromium")
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.user_agent)
                page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:  # noqa: BLE001 — browser errors are varied
            log.warning(f"Playwright fetch failed for {url}: {e}")
            return None

    # ── link discovery helper ──────────────────────────────────────────────────
    def discover_links(self, result: FetchResult, keywords: list[str]) -> list[str]:
        """Return absolute URLs on the page whose href/anchor text match keywords."""
        found: list[str] = []
        soup = result.soup()
        base = result.final_url
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            anchor = a.get_text(separator=" ").strip().lower()
            hay = f"{href.lower()} {anchor}"
            if any(kw in hay for kw in keywords):
                absolute = urljoin(base, href)
                if absolute not in found:
                    found.append(absolute)
        return found

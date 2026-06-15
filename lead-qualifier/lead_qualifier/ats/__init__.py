"""ATS registry + auto-detection.

To add a new ATS: implement an ATSProvider subclass in its own module and add
its class to PROVIDER_CLASSES below. Detection order follows the list.
"""

from __future__ import annotations

from typing import Optional

from ..utils.fetcher import Fetcher
from ..utils.logger import get_logger
from .ashby import AshbyATS
from .base import ATSProvider
from .greenhouse import GreenhouseATS
from .lever import LeverATS
from .recruitee import RecruiteeATS
from .workable import WorkableATS

log = get_logger("ats")

PROVIDER_CLASSES: list[type[ATSProvider]] = [
    GreenhouseATS,
    LeverATS,
    AshbyATS,
    WorkableATS,
    RecruiteeATS,
]


class ATSRegistry:
    def __init__(self, fetcher: Fetcher):
        self.providers: list[ATSProvider] = [cls(fetcher) for cls in PROVIDER_CLASSES]

    def detect(
        self, careers_url: str | None, page_html: str | None, domain: str
    ) -> tuple[Optional[ATSProvider], Optional[str]]:
        """Return (provider, token) for the first ATS that recognises the site."""
        for provider in self.providers:
            token = provider.detect(careers_url, page_html, domain)
            if token:
                log.info(f"Detected ATS '{provider.name}' (token={token}) for {domain}")
                return provider, token
        return None, None

"""HTTP access to douyu.com, with retry.

The only place in dykit that talks to douyu.com. Keeping it separate
means the parsing modules (room / server) stay pure enough to reason about,
and retry policy lives in exactly one file.
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger: logging.Logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

RETRY_ATTEMPTS_HTTP = 3
RETRY_BACKOFF_HTTP_MIN_SECONDS = 1
RETRY_BACKOFF_HTTP_MAX_SECONDS = 10
RETRY_BACKOFF_HTTP_MULTIPLIER = 2


@retry(
    retry=retry_if_exception_type(httpx.HTTPError),
    stop=stop_after_attempt(RETRY_ATTEMPTS_HTTP),
    wait=wait_exponential(
        multiplier=RETRY_BACKOFF_HTTP_MULTIPLIER,
        min=RETRY_BACKOFF_HTTP_MIN_SECONDS,
        max=RETRY_BACKOFF_HTTP_MAX_SECONDS,
    ),
    reraise=True,
)
def http_get(url: str, timeout: float) -> httpx.Response:
    """GET a douyu.com URL, retrying transport errors."""
    return httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
    )

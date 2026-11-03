"""Webpage fetching and text extraction (spec section 10).

Security rules:
- Only public http(s) URLs: localhost, private/link-local IPs, and
  non-web schemes are refused (SSRF protection).
- Responses are size-capped; text is extracted locally with the stdlib
  HTML parser (no JavaScript executed by the requests backend).
- Extracted content is returned as UNTRUSTED DATA with its source URL.

The optional Playwright backend renders JavaScript pages locally.
"""

from __future__ import annotations

import html as html_module
import ipaddress
import logging
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests

logger = logging.getLogger("jarvis.research.reader")

USER_AGENT = "JARVIS-PersonalAssistant/0.1 (+local research tool)"
SKIP_TAGS = {"script", "style", "noscript", "template"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


class WebContentError(RuntimeError):
    """Raised when a URL is refused or content cannot be retrieved."""


def validate_public_url(url: str) -> str:
    """Refuse non-http(s) schemes and non-public hosts (SSRF guard)."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise WebContentError(f"only http/https URLs are allowed: '{url}'")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise WebContentError(f"URL has no hostname: '{url}'")
    if hostname == "localhost" or hostname.endswith(".local"):
        raise WebContentError(f"local hosts are not allowed: '{url}'")
    try:
        address_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise WebContentError(f"cannot resolve host '{hostname}'") from exc
    for info in address_infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise WebContentError(
                f"host '{hostname}' resolves to a non-public address; refused"
            )
    return url.strip()


class _TextExtractor(HTMLParser):
    """Extracts visible text and the title from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, _attrs):
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text + " ")

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [line.strip() for line in raw.splitlines()]
        return html_module.unescape("\n".join(line for line in lines if line))


@dataclass(frozen=True)
class PageContent:
    """Extracted webpage content - untrusted data with its source."""

    url: str
    title: str
    text: str
    fetched_at: str
    truncated: bool = False
    engine: str = "requests"


class WebPageReader:
    """Reads public webpages and extracts text (requests backend)."""

    def __init__(
        self,
        max_bytes: int = 524_288,
        timeout_seconds: int = 20,
        session: requests.Session | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._timeout = timeout_seconds
        self._session = session if session is not None else requests.Session()

    @property
    def available(self) -> bool:
        return True

    def read(self, url: str) -> PageContent:
        """Fetch and extract a public webpage."""
        validate_public_url(url)
        from datetime import datetime, timezone

        try:
            response = self._session.get(
                url,
                timeout=self._timeout,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise WebContentError(
                f"failed to fetch '{url}': {type(exc).__name__}"
            ) from exc
        if response.status_code != 200:
            raise WebContentError(f"'{url}' returned HTTP {response.status_code}")
        # Re-validate after redirects (a redirect may target a private host).
        validate_public_url(str(response.url))
        content = response.text[: self._max_bytes]
        truncated = len(response.text) > self._max_bytes

        extractor = _TextExtractor()
        try:
            extractor.feed(content)
        except Exception as exc:
            logger.warning("HTML parse issue for %s: %s", url, exc)
        title = html_module.unescape(extractor.title.strip())
        return PageContent(
            url=str(response.url),
            title=title or url,
            text=extractor.text(),
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            truncated=truncated,
        )


class PlaywrightPageReader:
    """JavaScript-rendered page reader using Playwright (optional)."""

    def __init__(self, max_bytes: int = 524_288, timeout_seconds: int = 20) -> None:
        self._max_bytes = max_bytes
        self._timeout = timeout_seconds

    @property
    def available(self) -> bool:
        try:
            import playwright  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False

    def read(self, url: str) -> PageContent:
        """Render a page with a local headless Chromium and extract text."""
        validate_public_url(url)
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as exc:
            raise WebContentError(
                "playwright is not installed; install it and run "
                "'playwright install chromium' to use the browser backend"
            ) from exc
        from datetime import datetime, timezone

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=self._timeout * 1000)
                title = page.title()
                text = page.inner_text("body")
            finally:
                browser.close()
        return PageContent(
            url=url,
            title=title or url,
            text=text[: self._max_bytes],
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            truncated=len(text) > self._max_bytes,
            engine="playwright",
        )

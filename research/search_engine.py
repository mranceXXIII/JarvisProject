"""Web search via DuckDuckGo Lite (spec section 10).

Uses the lite HTML endpoint - a permitted access method with no API key or
account. Results are parsed from the HTML and returned as UNTRUSTED DATA
with source URLs. A custom provider/API can replace this class later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import requests

from research.webpage_reader import USER_AGENT

logger = logging.getLogger("jarvis.research.search")

DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"


@dataclass(frozen=True)
class SearchResult:
    """One web search hit."""

    title: str
    url: str
    snippet: str


class _ResultParser(HTMLParser):
    """Parses DuckDuckGo Lite anchors; decodes redirects; dedupes by URL."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[SearchResult] = []
        self._anchors: list[tuple[str, list[str]]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith(("http", "//", "/l/")):
                if self._current_href is not None:
                    self._anchors.append((self._current_href, self._current_text))
                self._current_href = href
                self._current_text = []

    def handle_data(self, data):
        if self._current_href is not None:
            text = data.strip()
            if text:
                self._current_text.append(text)

    @staticmethod
    def _decode_url(href: str) -> str:
        """Decode DDG redirect wrappers into the real result URL."""
        if href.startswith("//"):
            href = "https:" + href
        parsed = urlparse(href)
        if parsed.path.startswith("/l/"):
            params = parse_qs(parsed.query)
            if "uddg" in params:
                return unquote(params["uddg"][0])
        return href

    def _finalize(self) -> None:
        if self._current_href is not None:
            self._anchors.append((self._current_href, self._current_text))
            self._current_href = None
            self._current_text = []
        seen: set[str] = set()
        for href, text_parts in self._anchors:
            url = self._decode_url(href)
            if not url.startswith("http"):
                continue
            netloc = urlparse(url).netloc.lower()
            if "duckduckgo.com" in netloc:
                continue
            if url in seen:
                continue
            seen.add(url)
            title = text_parts[0] if text_parts else url
            snippet = " ".join(text_parts[1:])[:300]
            self.results.append(
                SearchResult(title=title, url=url, snippet=snippet)
            )

    def close(self) -> None:
        super().close()
        self._finalize()


class DuckDuckGoSearch:
    """Searches the public web through DuckDuckGo Lite."""

    def __init__(
        self,
        max_results: int = 5,
        timeout_seconds: int = 15,
        fetcher=None,
    ) -> None:
        self._max_results = max_results
        self._timeout = timeout_seconds
        self._fetcher = fetcher if fetcher is not None else self._default_fetcher

    @staticmethod
    def _default_fetcher(url: str, timeout: int) -> str:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str) -> list[SearchResult]:
        """Search the public web; results are untrusted data with sources."""
        query = query.strip()
        if not query:
            return []
        from urllib.parse import quote

        html = self._fetcher(f"{DDG_LITE_URL}?q={quote(query)}", self._timeout)
        parser = _ResultParser()
        parser.feed(html)
        parser.close()
        results = [
            r
            for r in parser.results
            if "duckduckgo.com" not in urlparse(r.url).netloc
        ]
        logger.info("web search %r returned %d results", query, len(results))
        return results[: self._max_results]

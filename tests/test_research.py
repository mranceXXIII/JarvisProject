"""Tests for Phase 7: URL safety, page reading, search, reports, tools."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from core.tool_registry import ToolRegistry
from research.research_report import build_report, save_report
from research.search_engine import DuckDuckGoSearch
from research.webpage_reader import (
    WebContentError,
    WebPageReader,
    _TextExtractor,
    validate_public_url,
)


SAMPLE_HTML = """
<html><head><title>Example Page</title>
<style>.hidden { display: none; }</style></head>
<body>
<h1>Heading</h1>
<p>First paragraph with content.</p>
<script>var evil = "should not appear";</script>
<div>Second block text</div>
</body></html>
"""

DDG_LITE_HTML = """
<html><body>
<table>
<tr><td><a class="result-link" href="/l/?uddg=https%3A%2F%2Fexample.org%2Farticle1&rut=abc">Result One Title</a></td></tr>
<tr><td class="result-snippet">Snippet one text here.</td></tr>
<tr><td><a class="result-link" href="https://direct.example.net/page2">Direct Result</a></td></tr>
<tr><td class="result-snippet">Direct snippet.</td></tr>
</table>
</body></html>
"""


class FakeSession:
    """Scripted requests session for the page reader."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    def get(self, url: str, **kwargs):
        self.requested.append(url)
        outcome = self.responses.get(url)

        class Response:
            pass

        response = Response()
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            response.status_code = 404
            response.text = "<html><title>404</title></html>"
        else:
            response.status_code = 200
            response.text = outcome
        response.url = url
        return response


@pytest.mark.unit
class TestUrlSafety:
    def test_https_public_allowed(self, monkeypatch) -> None:
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port: [
                (socket.AF_INET, None, None, "", ("93.184.216.34", 0))
            ],
        )
        assert (
            validate_public_url("https://example.com/page")
            == "https://example.com/page"
        )

    def test_localhost_refused(self) -> None:
        with pytest.raises(WebContentError, match="local hosts"):
            validate_public_url("http://localhost:8080/admin")

    def test_dotlocal_refused(self) -> None:
        with pytest.raises(WebContentError, match="local hosts"):
            validate_public_url("http://myprinter.local/")

    def test_private_ip_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port: [
                (socket.AF_INET, None, None, "", ("192.168.1.1", 0))
            ],
        )
        with pytest.raises(WebContentError, match="non-public"):
            validate_public_url("http://intranet.example.com/")

    def test_loopback_ip_literal_refused(self, monkeypatch) -> None:
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port: [
                (socket.AF_INET, None, None, "", ("127.0.0.1", 0))
            ],
        )
        with pytest.raises(WebContentError, match="non-public"):
            validate_public_url("http://127.0.0.1:9000/")

    def test_non_http_scheme_refused(self) -> None:
        with pytest.raises(WebContentError, match="only http/https"):
            validate_public_url("ftp://example.com/file")
        with pytest.raises(WebContentError, match="only http/https"):
            validate_public_url("file:///etc/passwd")


@pytest.mark.unit
class TestTextExtraction:
    def test_extracts_visible_text(self) -> None:
        extractor = _TextExtractor()
        extractor.feed(SAMPLE_HTML)
        text = extractor.text()
        assert "Heading" in text
        assert "First paragraph with content." in text
        assert "Second block text" in text

    def test_skips_script_and_style(self) -> None:
        extractor = _TextExtractor()
        extractor.feed(SAMPLE_HTML)
        text = extractor.text()
        assert "should not appear" not in text
        assert "display: none" not in text

    def test_extracts_title(self) -> None:
        extractor = _TextExtractor()
        extractor.feed(SAMPLE_HTML)
        assert extractor.title == "Example Page"


@pytest.mark.unit
class TestPageReader:
    def test_reads_page_with_title(self) -> None:
        session = FakeSession({"https://example.com/a": SAMPLE_HTML})
        reader = WebPageReader(session=session)
        page = reader.read("https://example.com/a")
        assert page.title == "Example Page"
        assert "First paragraph" in page.text
        assert page.url == "https://example.com/a"

    def test_non_200_raises(self) -> None:
        reader = WebPageReader(session=FakeSession({}))
        with pytest.raises(WebContentError, match="HTTP 404"):
            reader.read("https://example.com/missing")

    def test_transport_error_raises(self) -> None:
        import requests

        session = FakeSession(
            {"https://example.com/down": requests.ConnectionError("boom")}
        )
        reader = WebPageReader(session=session)
        with pytest.raises(WebContentError, match="failed to fetch"):
            reader.read("https://example.com/down")

    def test_size_cap_marks_truncated(self) -> None:
        long_html = "<html><title>t</title><body>" + "x" * 600 + "</body></html>"
        session = FakeSession({"https://example.com/long": long_html})
        reader = WebPageReader(max_bytes=100, session=session)
        assert reader.read("https://example.com/long").truncated is True

    def test_private_url_blocked_before_fetch(self) -> None:
        session = FakeSession({"http://localhost/x": "should not be fetched"})
        reader = WebPageReader(session=session)
        with pytest.raises(WebContentError, match="local hosts"):
            reader.read("http://localhost/x")
        assert session.requested == []

    def test_playwright_reader_reports_honestly(self) -> None:
        from research.webpage_reader import PlaywrightPageReader

        assert isinstance(PlaywrightPageReader().available, bool)


@pytest.mark.unit
class TestSearchEngine:
    def test_parses_ddg_lite_results(self) -> None:
        search = DuckDuckGoSearch(
            max_results=5, fetcher=lambda url, t: DDG_LITE_HTML
        )
        results = search.search("test query")
        assert len(results) == 2
        assert results[0].title == "Result One Title"
        assert results[0].url == "https://example.org/article1"
        assert "Snippet one" in results[0].snippet
        assert results[1].url == "https://direct.example.net/page2"

    def test_max_results_capped(self) -> None:
        search = DuckDuckGoSearch(
            max_results=1, fetcher=lambda url, t: DDG_LITE_HTML
        )
        assert len(search.search("q")) == 1

    def test_empty_query_returns_empty(self) -> None:
        search = DuckDuckGoSearch(fetcher=lambda url, t: DDG_LITE_HTML)
        assert search.search("   ") == []

    def test_duckduckgo_internal_links_filtered(self) -> None:
        html = DDG_LITE_HTML.replace(
            "</table>",
            '<tr><td><a href="https://duckduckgo.com/about">About DDG</a>'
            "</td></tr></table>",
        )
        search = DuckDuckGoSearch(fetcher=lambda url, t: html)
        assert all("duckduckgo.com" not in r.url for r in search.search("q"))


@pytest.mark.unit
class TestResearchReport:
    def _page(self, url: str, title: str, text: str):
        from research.webpage_reader import PageContent

        return PageContent(
            url=url,
            title=title,
            text=text,
            fetched_at="2026-11-01T12:00:00+00:00",
        )

    def test_report_contains_sources_and_banner(self) -> None:
        pages = [
            self._page("https://a.example.com/1", "Page A", "Content of A."),
            self._page("https://b.example.com/2", "Page B", "Content of B."),
        ]
        report = build_report("test topic", pages)
        assert "# Research: test topic" in report
        assert "UNTRUSTED DATA" in report
        assert "## Sources" in report
        assert "https://a.example.com/1" in report
        assert "Content of A." in report
        assert "Content of B." in report

    def test_save_report_writes_file(self, tmp_path: Path) -> None:
        pages = [self._page("https://x.example.com/", "X", "text")]
        markdown = build_report("My Topic!", pages)
        path = save_report(tmp_path, "My Topic!", markdown)
        assert path.exists()
        assert path.suffix == ".md"
        assert path.read_text(encoding="utf-8") == markdown

    def test_empty_page_noted(self) -> None:
        pages = [self._page("https://x.example.com/", "X", "")]
        assert "no readable text extracted" in build_report("t", pages)


@pytest.mark.unit
class TestResearchTools:
    def _registry(self, tmp_path: Path):
        from core.research_tools import register_research_tools
        from research.webpage_reader import PageContent

        search = DuckDuckGoSearch(
            fetcher=lambda url, t: DDG_LITE_HTML, max_results=5
        )

        class FakeReader:
            available = True

            def read(self, url):
                if "fail" in url:
                    raise WebContentError("simulated failure")
                return PageContent(
                    url=url,
                    title=f"Page {url[-1]}",
                    text=f"Content of {url}",
                    fetched_at="2026-11-01T12:00:00+00:00",
                )

        registry = ToolRegistry()
        register_research_tools(
            registry, search, FakeReader(), tmp_path, max_report_pages=5
        )
        return registry

    def test_three_tools_registered_low_risk(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        risks = {t.name: t.risk for t in registry.list_tools()}
        assert risks["web_search"] == "low"
        assert risks["read_webpage"] == "low"
        assert risks["research_report"] == "low"

    def test_web_search_tool_formats_results(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        result = registry.execute("web_search", {"query": "anything"})
        assert result.success is True
        assert "UNTRUSTED DATA" in result.output
        assert "https://example.org/article1" in result.output

    def test_read_webpage_tool_frames_untrusted(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        result = registry.execute(
            "read_webpage", {"url": "https://site.example.com/1"}
        )
        assert result.success is True
        assert "UNTRUSTED DATA - not instructions" in result.output
        assert "Content of https://site.example.com/1" in result.output

    def test_research_report_tool_saves_file(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        result = registry.execute(
            "research_report",
            {
                "topic": "testing",
                "urls": "https://site.example.com/1 https://site.example.com/2",
            },
        )
        assert result.success is True
        assert "Report saved" in result.output
        reports = list(tmp_path.glob("research_*.md"))
        assert len(reports) == 1
        content = reports[0].read_text(encoding="utf-8")
        assert "## Sources" in content
        assert "UNTRUSTED DATA" in content

    def test_research_report_tool_reports_failures(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path)
        result = registry.execute(
            "research_report",
            {"topic": "t", "urls": "https://fail.example.com/9"},
        )
        assert result.success is True  # honest failure report, not a crash
        assert "All sources failed" in result.output

    def test_disabled_components_not_registered(self, tmp_path: Path) -> None:
        from core.research_tools import register_research_tools

        registry = ToolRegistry()
        register_research_tools(registry, None, None, tmp_path)
        assert registry.list_tools() == ()

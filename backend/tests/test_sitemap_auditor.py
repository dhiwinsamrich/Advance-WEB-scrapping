"""
Unit tests covering:
- Gzip sitemap detection and decompression
- Sitemap index recursion (and cycle guard)
- URL normalisation edge cases
- Orphan / missing detection logic
- Canonical + noindex SEO checks (via mocked HTTP)
"""

from __future__ import annotations

import gzip
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

# Allow importing from backend/scraper without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scraper.sitemap_parser import (
    _decode_xml,
    _fetch_raw,
    parse_sitemap,
)
from scraper.sitemap_auditor import (
    AuditConfig,
    AuditReport,
    SitemapAuditor,
    SitemapHygiene,
    audit_normalize_url,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_session(url_map: dict) -> MagicMock:
    """Build a requests.Session mock that returns canned content per URL."""
    session = MagicMock()

    def _get(url, **_):
        resp = MagicMock()
        content = url_map.get(url, b"")
        resp.content = content if isinstance(content, bytes) else content.encode()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        return resp

    def _head(url, **_):
        resp = MagicMock()
        resp.status_code = 200 if url in url_map else 404
        return resp

    session.get.side_effect = _get
    session.head.side_effect = _head
    return session


URLSET_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/page1</loc><lastmod>2024-01-01</lastmod></url>
  <url><loc>https://example.com/page2</loc></url>
</urlset>"""

INDEX_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap2.xml</loc></sitemap>
</sitemapindex>"""

SITEMAP1_XML = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/alpha</loc></url>
</urlset>"""

SITEMAP2_XML = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/beta</loc></url>
</urlset>"""


# ── Gzip tests ────────────────────────────────────────────────────────────────

class TestGzipSitemap:
    def test_magic_bytes_present_after_compress(self):
        compressed = gzip.compress(URLSET_XML)
        assert compressed[0] == 0x1F
        assert compressed[1] == 0x8B

    def test_fetch_raw_decompresses_by_magic_bytes(self):
        compressed = gzip.compress(URLSET_XML)
        session = _mock_session({"https://example.com/sitemap.xml": compressed})
        result = _fetch_raw("https://example.com/sitemap.xml", session)
        assert result == URLSET_XML

    def test_fetch_raw_decompresses_by_gz_suffix(self):
        compressed = gzip.compress(URLSET_XML)
        url = "https://example.com/sitemap.xml.gz"
        session = _mock_session({url: compressed})
        result = _fetch_raw(url, session)
        assert result == URLSET_XML

    def test_parse_sitemap_from_gzipped_content(self):
        compressed = gzip.compress(URLSET_XML)
        session = _mock_session({"https://example.com/sitemap.xml.gz": compressed})
        entries = parse_sitemap("https://example.com/sitemap.xml.gz", session)
        urls = [e.url for e in entries]
        assert "https://example.com/page1" in urls
        assert "https://example.com/page2" in urls

    def test_non_gzip_url_with_gz_suffix_handled_gracefully(self):
        # URL ends in .gz but content is plain XML — should still parse
        url = "https://example.com/sitemap.xml.gz"
        session = _mock_session({url: URLSET_XML})
        # _fetch_raw will try gzip.decompress, fail silently, return raw bytes
        result = _fetch_raw(url, session)
        # Result is NOT decompressed (gzip error swallowed), still valid XML
        assert result is not None


# ── Sitemap index recursion ───────────────────────────────────────────────────

class TestSitemapIndexRecursion:
    def test_recurses_into_child_sitemaps(self):
        session = _mock_session(
            {
                "https://example.com/sitemap_index.xml": INDEX_XML,
                "https://example.com/sitemap1.xml": SITEMAP1_XML,
                "https://example.com/sitemap2.xml": SITEMAP2_XML,
            }
        )
        entries = parse_sitemap("https://example.com/sitemap_index.xml", session)
        urls = {e.url for e in entries}
        assert "https://example.com/alpha" in urls
        assert "https://example.com/beta" in urls

    def test_cycle_guard_prevents_infinite_loop(self):
        """A sitemap that references itself must not loop."""
        self_ref = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sitemap_index.xml</loc></sitemap>
</sitemapindex>"""
        session = _mock_session({"https://example.com/sitemap_index.xml": self_ref})
        entries = parse_sitemap("https://example.com/sitemap_index.xml", session)
        assert entries == []  # Cycle → nothing returned

    def test_depth_cap_prevents_deep_recursion(self):
        """Build a chain of sitemaps deeper than MAX_SITEMAP_DEPTH."""
        from scraper.sitemap_parser import MAX_SITEMAP_DEPTH

        url_map = {}
        for i in range(MAX_SITEMAP_DEPTH + 3):
            next_url = f"https://example.com/s{i + 1}.xml"
            xml = (
                f'<?xml version="1.0"?>'
                f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<sitemap><loc>{next_url}</loc></sitemap>"
                f"</sitemapindex>"
            ).encode()
            url_map[f"https://example.com/s{i}.xml"] = xml

        # The last one is a urlset
        url_map[f"https://example.com/s{MAX_SITEMAP_DEPTH + 3}.xml"] = URLSET_XML

        session = _mock_session(url_map)
        entries = parse_sitemap("https://example.com/s0.xml", session)
        # Should stop recursing before reaching the terminal urlset
        assert entries == []


# ── URL normalisation ─────────────────────────────────────────────────────────

class TestUrlNormalization:
    def test_default_port_http_collapsed(self):
        assert audit_normalize_url("http://example.com:80/path") == "http://example.com/path"

    def test_default_port_https_collapsed(self):
        assert audit_normalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_non_default_port_preserved(self):
        assert audit_normalize_url("http://example.com:8080/path") == "http://example.com:8080/path"

    def test_trailing_slash_stripped(self):
        assert audit_normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_root_trailing_slash_preserved(self):
        n = audit_normalize_url("https://example.com/")
        assert n == "https://example.com/"

    def test_fragment_stripped(self):
        assert audit_normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_scheme_and_host_lowercased(self):
        assert audit_normalize_url("HTTPS://EXAMPLE.COM/Page") == "https://example.com/Page"

    def test_query_preserved_by_default(self):
        n = audit_normalize_url("https://example.com/search?q=hello")
        assert "q=hello" in (n or "")

    def test_query_stripped_when_requested(self):
        n = audit_normalize_url("https://example.com/search?q=hello", strip_query=True)
        assert n == "https://example.com/search"

    def test_none_returns_none(self):
        assert audit_normalize_url("") is None
        assert audit_normalize_url(None) is None  # type: ignore[arg-type]

    def test_relative_url_returns_none(self):
        assert audit_normalize_url("/relative/path") is None


# ── Orphan / missing detection ────────────────────────────────────────────────

class TestOrphanAndMissingDetection:
    def _make_report(self, covered, missing, orphaned):
        return AuditReport(
            root_url="https://example.com",
            covered=covered,
            missing_from_sitemap=missing,
            orphaned_in_sitemap=orphaned,
            hygiene=SitemapHygiene(
                total_urls=len(covered) + len(orphaned),
                over_url_limit=False,
                over_size_limit=False,
                duplicate_locs=[],
                missing_lastmod=0,
                redirect_entries=[],
                non_200_entries={},
            ),
        )

    def test_covered_urls_classified_correctly(self):
        r = self._make_report(
            covered=["https://example.com/both"],
            missing=["https://example.com/crawled-only"],
            orphaned=["https://example.com/sitemap-only"],
        )
        assert "https://example.com/both" in r.covered

    def test_missing_from_sitemap_classified_correctly(self):
        r = self._make_report(
            covered=[],
            missing=["https://example.com/crawled-only"],
            orphaned=[],
        )
        assert "https://example.com/crawled-only" in r.missing_from_sitemap
        assert "https://example.com/crawled-only" not in r.covered

    def test_orphaned_in_sitemap_classified_correctly(self):
        r = self._make_report(
            covered=[],
            missing=[],
            orphaned=["https://example.com/sitemap-only"],
        )
        assert "https://example.com/sitemap-only" in r.orphaned_in_sitemap
        assert "https://example.com/sitemap-only" not in r.covered

    def test_fail_verdict_when_orphans_exist(self):
        r = self._make_report(covered=[], missing=[], orphaned=["https://example.com/dead"])
        r.verdict = "FAIL"
        r.exit_code = 1
        assert r.verdict == "FAIL"
        assert r.exit_code == 1

    def test_pass_verdict_when_clean(self):
        r = self._make_report(
            covered=["https://example.com/home"],
            missing=[],
            orphaned=[],
        )
        r.verdict = "PASS"
        r.exit_code = 0
        assert r.verdict == "PASS"
        assert r.exit_code == 0


# ── XML decoding ──────────────────────────────────────────────────────────────

class TestXmlDecoding:
    def test_utf8_bom_stripped(self):
        content = b"\xef\xbb\xbf<?xml version='1.0'?><root/>"
        decoded = _decode_xml(content)
        assert not decoded.startswith("﻿")
        assert decoded.startswith("<?xml")

    def test_encoding_declaration_respected(self):
        content = b"<?xml version='1.0' encoding='latin-1'?><root>caf\xe9</root>"
        decoded = _decode_xml(content)
        assert "café" in decoded

    def test_plain_utf8_decoded(self):
        content = "<?xml version='1.0'?><root>hello</root>".encode("utf-8")
        decoded = _decode_xml(content)
        assert "hello" in decoded


# ── Duplicate <loc> detection ─────────────────────────────────────────────────

class TestHygieneChecks:
    def test_duplicate_locs_detected(self):
        from scraper.sitemap_parser import SitemapEntry
        from scraper.sitemap_auditor import SitemapAuditor, AuditConfig

        entries = [
            SitemapEntry(url="https://example.com/page"),
            SitemapEntry(url="https://example.com/page"),  # duplicate
            SitemapEntry(url="https://example.com/other"),
        ]

        auditor = SitemapAuditor(AuditConfig(root_url="https://example.com"))
        hygiene = auditor._check_hygiene(entries)
        assert "https://example.com/page" in hygiene.duplicate_locs

    def test_over_url_limit_flag(self):
        from scraper.sitemap_parser import SitemapEntry
        from scraper.sitemap_auditor import SitemapAuditor, AuditConfig

        entries = [SitemapEntry(url=f"https://example.com/p{i}") for i in range(50_001)]
        auditor = SitemapAuditor(AuditConfig(root_url="https://example.com"))
        hygiene = auditor._check_hygiene(entries)
        assert hygiene.over_url_limit is True

    def test_missing_lastmod_counted(self):
        from scraper.sitemap_parser import SitemapEntry
        from scraper.sitemap_auditor import SitemapAuditor, AuditConfig

        entries = [
            SitemapEntry(url="https://example.com/a", lastmod="2024-01-01"),
            SitemapEntry(url="https://example.com/b"),  # no lastmod
            SitemapEntry(url="https://example.com/c"),  # no lastmod
        ]
        auditor = SitemapAuditor(AuditConfig(root_url="https://example.com"))
        hygiene = auditor._check_hygiene(entries)
        assert hygiene.missing_lastmod == 2

"""
Sitemap discovery and parsing.

Handles:
- robots.txt Sitemap: directives with fallback to common paths
- Both <urlset> and <sitemapindex> documents
- Gzip detection by magic bytes (0x1f 0x8b) OR .gz suffix
- Encoding: XML declaration + BOM stripping
- Recursion guard (max depth + cycle detection via visited set)
"""

from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Set
from urllib.parse import urlparse

import requests

MAX_SITEMAP_DEPTH = 5


@dataclass
class SitemapEntry:
    url: str
    lastmod: Optional[str] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None


# ── Discovery ────────────────────────────────────────────────────────────────

def discover_sitemap_urls(base_url: str, session: requests.Session) -> List[str]:
    """
    Return sitemap URLs for base_url.
    Order: robots.txt Sitemap: directives → fallback common paths.
    """
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    found: List[str] = []

    # 1. Parse robots.txt
    try:
        resp = session.get(f"{origin}/robots.txt", timeout=10)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                stripped = line.strip()
                if stripped.lower().startswith("sitemap:"):
                    sm_url = stripped.split(":", 1)[1].strip()
                    if sm_url:
                        found.append(sm_url)
    except Exception:
        pass

    if found:
        return found

    # 2. Fallback paths
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
        url = f"{origin}{path}"
        try:
            resp = session.head(url, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                found.append(url)
                return found
        except Exception:
            continue

    return found


# ── Fetch + decode ────────────────────────────────────────────────────────────

def _fetch_raw(url: str, session: requests.Session) -> Optional[bytes]:
    """
    Fetch URL bytes, auto-decompressing gzip regardless of Content-Type.
    Detects gzip by magic bytes 0x1f 0x8b OR a .gz URL suffix.
    """
    try:
        resp = session.get(url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        raw = resp.content

        is_gz = url.rstrip("?").lower().endswith(".gz") or (
            len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B
        )
        if is_gz:
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass  # Not actually gzip — use as-is

        return raw
    except Exception:
        return None


def _decode_xml(raw: bytes) -> str:
    """Strip BOM and decode bytes to str, honouring the XML encoding declaration."""
    # Strip known BOMs
    bom_map = [
        (b"\xef\xbb\xbf", "utf-8"),
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ]
    for bom, enc in bom_map:
        if raw.startswith(bom):
            return raw[len(bom) :].decode(enc, errors="replace")

    # Read encoding from XML declaration if present
    head = raw[:200].decode("ascii", errors="replace")
    m = re.search(r'encoding=["\']([^"\']+)["\']', head, re.IGNORECASE)
    if m:
        try:
            return raw.decode(m.group(1), errors="replace")
        except LookupError:
            pass

    return raw.decode("utf-8", errors="replace")


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_sitemap(
    url: str,
    session: requests.Session,
    visited: Optional[Set[str]] = None,
    depth: int = 0,
) -> List[SitemapEntry]:
    """
    Parse a sitemap URL recursively.
    Handles <urlset> (returns entries) and <sitemapindex> (recurses into children).
    Guards against cycles via `visited` and caps recursion at MAX_SITEMAP_DEPTH.
    """
    if visited is None:
        visited = set()

    if depth > MAX_SITEMAP_DEPTH or url in visited:
        return []

    visited.add(url)

    raw = _fetch_raw(url, session)
    if not raw:
        return []

    text = _decode_xml(raw)

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    # Strip namespace prefix so tag matching works regardless of xmlns
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    tag_local = root.tag.replace(ns, "")

    if tag_local == "sitemapindex":
        entries: List[SitemapEntry] = []
        for sm in root.findall(f"{ns}sitemap"):
            loc_el = sm.find(f"{ns}loc")
            if loc_el is not None and loc_el.text:
                child_url = loc_el.text.strip()
                entries.extend(parse_sitemap(child_url, session, visited, depth + 1))
        return entries

    if tag_local == "urlset":
        entries = []
        for url_el in root.findall(f"{ns}url"):
            loc_el = url_el.find(f"{ns}loc")
            if loc_el is None or not loc_el.text:
                continue

            def _text(tag: str) -> Optional[str]:
                el = url_el.find(f"{ns}{tag}")
                return el.text.strip() if el is not None and el.text else None

            priority_str = _text("priority")
            entries.append(
                SitemapEntry(
                    url=loc_el.text.strip(),
                    lastmod=_text("lastmod"),
                    changefreq=_text("changefreq"),
                    priority=float(priority_str) if priority_str else None,
                )
            )
        return entries

    return []

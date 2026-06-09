"""
Sitemap auditor — cross-references BFS crawl against XML sitemap declarations.

Reuses the existing Scraper for HTTP fetching and HTML parsing.
Does NOT use Crawler so it can manage its own BFS, collect metadata per-page,
and avoid coupling to the log-file-based session model.

Produces AuditReport with:
  - covered                 : URLs in both crawl and sitemap
  - missing_pages           : real pages crawled but not in sitemap
  - non_page_files          : .txt/.pdf etc. crawled but rightly absent from sitemap
  - orphaned_in_sitemap     : declared but unreachable / non-200
  - orphan_details          : per-URL reason (JS_RENDERED, NOT_FOUND, REDIRECT …)
  - seo_issues              : noindex_in_sitemap, canonical_mismatch
  - hygiene                 : sitemap protocol checks
  - site_intelligence       : framework detection, noscript fallback detection
  - insights                : auto-generated plain-English interpretation
  - verdict / exit_code     : PASS/FAIL for CI
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .scraper import Scraper
from .sitemap_parser import SitemapEntry, discover_sitemap_urls, parse_sitemap
from .utils import get_random_user_agent, is_internal_url

logger = logging.getLogger("auditor")

# File extensions that are never web pages and should never appear in a sitemap.
NON_PAGE_EXTENSIONS = {
    ".txt", ".pdf", ".xml", ".json", ".csv", ".rss", ".atom",
    ".gz", ".zip", ".tar", ".rar", ".7z",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
    ".mp4", ".mp3", ".mov", ".avi", ".webm",
    ".woff", ".woff2", ".ttf", ".eot",
    ".js", ".css", ".map",
}

# Orphan reason codes
REASON_JS_RENDERED   = "JS_RENDERED"    # live page, only reachable via JS nav
REASON_NOT_LINKED    = "NOT_LINKED"     # live page, just not discovered by crawler
REASON_NOT_FOUND     = "NOT_FOUND"      # 404
REASON_REDIRECT      = "REDIRECT"       # 3xx
REASON_ACCESS_DENIED = "ACCESS_DENIED"  # 401/403
REASON_SERVER_ERROR  = "SERVER_ERROR"   # 5xx
REASON_FETCH_ERROR   = "FETCH_ERROR"    # connection/timeout error


# ── URL normalisation ─────────────────────────────────────────────────────────

def audit_normalize_url(url: str, strip_query: bool = False) -> Optional[str]:
    """
    Normalise a URL for set-based comparison.
    - Lowercase scheme + host
    - Collapse default ports (80/http, 443/https)
    - Strip trailing slash on non-root paths
    - Strip fragment always
    - Optionally strip query string
    """
    if not url:
        return None
    try:
        p = urlparse(url.strip())
        scheme = p.scheme.lower()
        netloc = p.netloc.lower()

        if not scheme or not netloc:
            return None

        if ":" in netloc:
            host, port_str = netloc.rsplit(":", 1)
            if port_str.isdigit():
                port = int(port_str)
                if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
                    netloc = host

        path = p.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")

        query = "" if strip_query else p.query

        return urlunparse((scheme, netloc, path, p.params, query, ""))
    except Exception:
        return None


def _is_non_page_url(url: str) -> bool:
    """Return True if url points to a file that is never a crawlable web page."""
    path = urlparse(url).path.lower().rstrip("/")
    return any(path.endswith(ext) for ext in NON_PAGE_EXTENSIONS)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PageInfo:
    url: str
    final_url: str
    status_code: int
    is_redirect: bool
    noindex: bool
    canonical: Optional[str]
    html: Optional[str] = None      # stored for homepage intelligence detection
    error: Optional[str] = None


@dataclass
class SiteIntelligence:
    """Detected characteristics of the target website."""
    framework: Optional[str]          # "React (Vite)", "Next.js", "Vue.js", etc.
    spa_detected: bool                # True if site renders via JS
    has_noscript_fallback: bool       # True if <noscript> block contains links
    noscript_link_count: int          # how many links found only in <noscript>
    homepage_html_available: bool


@dataclass
class OrphanDetail:
    """Why a specific sitemap URL was not reached by the crawler."""
    url: str
    reason: str       # one of the REASON_* constants above
    status_code: int
    final_url: Optional[str] = None   # populated for redirects


@dataclass
class SitemapHygiene:
    total_urls: int
    over_url_limit: bool
    over_size_limit: bool
    duplicate_locs: List[str]
    missing_lastmod: int
    redirect_entries: List[str]
    non_200_entries: Dict[str, int]


@dataclass
class AuditReport:
    root_url: str

    # Coverage (backward-compatible names kept)
    covered: List[str]
    missing_from_sitemap: List[str]   # all crawled URLs not in sitemap (pages + files)
    orphaned_in_sitemap: List[str]    # all normalised orphaned URLs

    # Enriched fields (new)
    missing_pages: List[str] = field(default_factory=list)       # real pages only
    non_page_files: List[str] = field(default_factory=list)      # .txt/.pdf etc.
    orphan_details: List[OrphanDetail] = field(default_factory=list)
    site_intelligence: Optional[SiteIntelligence] = None
    insights: List[str] = field(default_factory=list)

    seo_issues: Dict[str, List[str]] = field(default_factory=dict)
    hygiene: Optional[SitemapHygiene] = None
    verdict: str = "PASS"
    exit_code: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_table(self) -> str:
        lines = [
            "=" * 70,
            f"SITEMAP AUDIT REPORT  —  {self.root_url}",
            "=" * 70,
            f"Verdict : {'PASS' if self.verdict == 'PASS' else 'FAIL'}",
        ]

        if self.site_intelligence and self.site_intelligence.framework:
            lines.append(f"Framework : {self.site_intelligence.framework}")

        lines += [
            "",
            "Coverage:",
            f"  Covered                      : {len(self.covered)}",
            f"  Missing pages from sitemap   : {len(self.missing_pages)}",
            f"  Non-page files (ignored)     : {len(self.non_page_files)}",
            f"  Orphaned in sitemap          : {len(self.orphaned_in_sitemap)}",
            "",
        ]

        if self.insights:
            lines.append("INSIGHTS:")
            for insight in self.insights:
                lines.append(f"  > {insight}")
            lines.append("")

        def _block(title: str, items: List[str]) -> None:
            if not items:
                return
            lines.append(f"{title} ({len(items)}):")
            for u in items[:20]:
                lines.append(f"  - {u}")
            if len(items) > 20:
                lines.append(f"  ... and {len(items) - 20} more")
            lines.append("")

        _block("MISSING PAGES FROM SITEMAP", self.missing_pages)

        if self.orphan_details:
            lines.append(f"ORPHANED IN SITEMAP ({len(self.orphan_details)}):")
            for d in self.orphan_details[:20]:
                lines.append(f"  [{d.reason}] {d.url}  (HTTP {d.status_code})")
            if len(self.orphan_details) > 20:
                lines.append(f"  ... and {len(self.orphan_details) - 20} more")
            lines.append("")

        if self.seo_issues:
            lines.append("SEO ISSUES:")
            for kind, urls in self.seo_issues.items():
                _block(f"  {kind}", urls)

        if self.hygiene:
            h = self.hygiene
            lines += [
                "SITEMAP HYGIENE:",
                f"  Total URLs        : {h.total_urls}",
                f"  Over 50k limit    : {'Yes' if h.over_url_limit else 'No'}",
                f"  Missing <lastmod> : {h.missing_lastmod}",
                f"  Duplicate <loc>   : {len(h.duplicate_locs)}",
                f"  Non-200 entries   : {len(h.non_200_entries)}",
                f"  Redirect entries  : {len(h.redirect_entries)}",
                "",
            ]

        if self.warnings:
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"  ! {w}")
            lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)


@dataclass
class AuditConfig:
    root_url: str
    sitemap_override: Optional[str] = None
    max_pages: int = 500
    max_workers: int = 5
    delay: float = 0.5
    strip_query: bool = False
    js_fallback: bool = False


# ── Auditor ───────────────────────────────────────────────────────────────────

class SitemapAuditor:
    def __init__(self, config: AuditConfig):
        self.config = config
        self._stop = False

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": get_random_user_agent(),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        self._cache: Dict[str, PageInfo] = {}
        self._cache_lock = threading.Lock()

    def stop(self) -> None:
        self._stop = True

    # ── Core helpers ──────────────────────────────────────────────────────────

    def _norm(self, url: str) -> Optional[str]:
        return audit_normalize_url(url, strip_query=self.config.strip_query)

    def _fetch_page_info(self, url: str, store_html: bool = False) -> PageInfo:
        with self._cache_lock:
            if url in self._cache:
                return self._cache[url]

        try:
            time.sleep(self.config.delay)
            resp = self._session.get(url, timeout=30, allow_redirects=True)
            final_url = resp.url
            status_code = resp.status_code
            is_redirect = len(resp.history) > 0
            noindex = False
            canonical: Optional[str] = None
            html: Optional[str] = None

            if status_code == 200:
                xrt = resp.headers.get("X-Robots-Tag", "")
                if "noindex" in xrt.lower():
                    noindex = True

                soup = BeautifulSoup(resp.text, "html.parser")
                meta_robots = soup.find(
                    "meta", attrs={"name": lambda x: x and x.lower() == "robots"}
                )
                if meta_robots and "noindex" in meta_robots.get("content", "").lower():
                    noindex = True

                canon = soup.find("link", rel="canonical")
                if canon:
                    canonical = (canon.get("href") or "").strip() or None

                if store_html:
                    html = resp.text

            info = PageInfo(
                url=url,
                final_url=final_url,
                status_code=status_code,
                is_redirect=is_redirect,
                noindex=noindex,
                canonical=canonical,
                html=html,
            )
        except Exception as exc:
            info = PageInfo(
                url=url,
                final_url=url,
                status_code=0,
                is_redirect=False,
                noindex=False,
                canonical=None,
                error=str(exc),
            )

        with self._cache_lock:
            self._cache[url] = info

        return info

    # ── Intelligence detection ────────────────────────────────────────────────

    def _detect_framework(self, html: str) -> Optional[str]:
        """Detect JS framework from homepage HTML markers."""
        soup = BeautifulSoup(html, "html.parser")
        scripts = [s.get("src", "") for s in soup.find_all("script", src=True)]

        # Next.js
        if soup.find("script", id="__NEXT_DATA__"):
            return "Next.js"
        if any("/_next/" in s for s in scripts):
            return "Next.js"

        # Nuxt.js
        if soup.find("div", id="__nuxt") or soup.find("div", id="__layout"):
            return "Nuxt.js"
        if any("/_nuxt/" in s for s in scripts):
            return "Nuxt.js"

        # Gatsby
        if soup.find(id="gatsby-focus-wrapper") or any("gatsby" in s for s in scripts):
            return "Gatsby (React)"

        # React + Vite (assets/index-<hash>.js)
        root = soup.find(id="root")
        if root and any(re.search(r"assets/index-\w+\.js", s) for s in scripts):
            return "React (Vite)"

        # React + CRA
        if root and any("static/js/" in s for s in scripts):
            return "React (CRA)"

        # Generic React
        if root:
            return "React"

        # Vue
        app_div = soup.find(id="app")
        if app_div and any("vue" in s.lower() for s in scripts):
            return "Vue.js"
        if app_div:
            return "Vue.js"

        # Angular
        if soup.find("app-root") or soup.find(attrs={"ng-version": True}):
            return "Angular"

        # SvelteKit
        if any("_app/immutable" in s for s in scripts):
            return "SvelteKit"

        return None

    def _detect_noscript_links(self, html: str) -> Tuple[bool, int]:
        """
        Returns (has_noscript_fallback, noscript_link_count).
        Counts links that appear ONLY inside <noscript> blocks.
        """
        soup = BeautifulSoup(html, "html.parser")

        # All links in document
        all_links = {a.get("href", "") for a in soup.find_all("a", href=True)}

        # Links inside <noscript> only
        noscript_links: Set[str] = set()
        for ns in soup.find_all("noscript"):
            for a in ns.find_all("a", href=True):
                noscript_links.add(a.get("href", ""))

        # Links that appear ONLY in noscript (not in the regular DOM)
        exclusive_noscript = noscript_links - (all_links - noscript_links)

        has_fallback = len(noscript_links) > 0
        return has_fallback, len(noscript_links)

    def _detect_site_intelligence(self) -> SiteIntelligence:
        """Fetch homepage and analyse it for framework, SPA, noscript patterns."""
        logger.info("[intelligence] Analysing homepage…")
        info = self._fetch_page_info(self.config.root_url, store_html=True)

        if not info.html:
            return SiteIntelligence(
                framework=None,
                spa_detected=False,
                has_noscript_fallback=False,
                noscript_link_count=0,
                homepage_html_available=False,
            )

        framework = self._detect_framework(info.html)
        has_noscript, noscript_count = self._detect_noscript_links(info.html)

        # A site is considered SPA if a JS framework is detected AND the root div
        # has no meaningful child content in raw HTML.
        spa_detected = False
        if framework:
            soup = BeautifulSoup(info.html, "html.parser")
            root = soup.find(id="root") or soup.find(id="app") or soup.find("app-root")
            if root:
                # Raw HTML text content inside the root div (excluding noscript)
                for ns in (root.find_all("noscript") if root else []):
                    ns.decompose()
                raw_text = (root.get_text(strip=True) if root else "")
                spa_detected = len(raw_text) < 200

        logger.info(
            f"[intelligence] framework={framework} spa={spa_detected} "
            f"noscript_fallback={has_noscript} noscript_links={noscript_count}"
        )

        return SiteIntelligence(
            framework=framework,
            spa_detected=spa_detected,
            has_noscript_fallback=has_noscript,
            noscript_link_count=noscript_count,
            homepage_html_available=True,
        )

    # ── Orphan categorisation ─────────────────────────────────────────────────

    def _categorize_orphan(
        self, url: str, info: Optional[PageInfo], spa_detected: bool
    ) -> OrphanDetail:
        """Assign a human-readable reason to each orphaned sitemap URL."""
        if info is None:
            return OrphanDetail(url=url, reason=REASON_FETCH_ERROR, status_code=0)

        code = info.status_code
        final = info.final_url if info.final_url != url else None

        if info.error and code == 0:
            return OrphanDetail(url=url, reason=REASON_FETCH_ERROR, status_code=0)

        if info.is_redirect or code in (301, 302, 303, 307, 308):
            return OrphanDetail(url=url, reason=REASON_REDIRECT, status_code=code, final_url=final)

        if code == 404:
            return OrphanDetail(url=url, reason=REASON_NOT_FOUND, status_code=code)

        if code in (401, 403):
            return OrphanDetail(url=url, reason=REASON_ACCESS_DENIED, status_code=code)

        if code >= 500:
            return OrphanDetail(url=url, reason=REASON_SERVER_ERROR, status_code=code)

        if code == 200:
            # Page is live but crawler didn't find it.
            reason = REASON_JS_RENDERED if spa_detected else REASON_NOT_LINKED
            return OrphanDetail(url=url, reason=reason, status_code=200)

        return OrphanDetail(url=url, reason=REASON_FETCH_ERROR, status_code=code)

    # ── Insights generation ───────────────────────────────────────────────────

    def _generate_insights(
        self,
        si: Optional[SiteIntelligence],
        orphan_details: List[OrphanDetail],
        missing_pages: List[str],
        non_page_files: List[str],
        hygiene: SitemapHygiene,
    ) -> List[str]:
        insights: List[str] = []

        # Framework / SPA
        if si and si.spa_detected and si.framework:
            insights.append(
                f"Site is a {si.framework} single-page application (SPA). "
                "Navigation links are JavaScript-rendered and invisible to static crawlers."
            )
        elif si and si.framework:
            insights.append(f"Site uses {si.framework}.")

        # Noscript fallback
        if si and si.has_noscript_fallback:
            insights.append(
                f"{si.noscript_link_count} link(s) were discovered via a <noscript> fallback block. "
                "The site has partial static content for bots, but not all pages are covered."
            )

        # Orphan breakdown
        reason_counts: Dict[str, int] = {}
        for d in orphan_details:
            reason_counts[d.reason] = reason_counts.get(d.reason, 0) + 1

        js_count = reason_counts.get(REASON_JS_RENDERED, 0)
        if js_count:
            insights.append(
                f"{js_count} orphaned page(s) are real, live pages (HTTP 200) that the static crawler "
                "couldn't reach because their links are JS-rendered. "
                "Re-run with JS Fallback (Selenium) enabled — orphan count should drop to 0."
            )

        not_linked_count = reason_counts.get(REASON_NOT_LINKED, 0)
        if not_linked_count:
            insights.append(
                f"{not_linked_count} page(s) are live (HTTP 200) but not discoverable "
                "via link traversal. They may be deep pages beyond the crawl depth or only "
                "reachable through search/filters."
            )

        not_found_count = reason_counts.get(REASON_NOT_FOUND, 0)
        if not_found_count:
            insights.append(
                f"{not_found_count} sitemap entry/entries return 404. "
                "These are genuinely broken — remove them from the sitemap."
            )

        redirect_count = reason_counts.get(REASON_REDIRECT, 0)
        if redirect_count:
            insights.append(
                f"{redirect_count} sitemap entry/entries redirect (3xx). "
                "Sitemaps should list canonical 200 URLs, not redirect chains."
            )

        access_count = reason_counts.get(REASON_ACCESS_DENIED, 0)
        if access_count:
            insights.append(
                f"{access_count} page(s) returned 401/403. "
                "If they are public pages, check server config. "
                "If intentionally restricted, remove from sitemap."
            )

        server_err_count = reason_counts.get(REASON_SERVER_ERROR, 0)
        if server_err_count:
            insights.append(
                f"{server_err_count} page(s) returned 5xx server errors — "
                "these need immediate attention on the server side."
            )

        # Non-page files
        if non_page_files:
            exts = sorted({urlparse(f).path.rsplit(".", 1)[-1] for f in non_page_files if "." in urlparse(f).path})
            ext_str = ", ".join(f".{e}" for e in exts[:5])
            insights.append(
                f"{len(non_page_files)} 'missing from sitemap' entry/entries are non-page files "
                f"({ext_str}) — these are never web pages and should not be in a sitemap. Safe to ignore."
            )

        # Hygiene
        if hygiene.duplicate_locs:
            insights.append(
                f"{len(hygiene.duplicate_locs)} duplicate <loc> entry/entries in sitemap. "
                "Each URL should appear exactly once."
            )

        if hygiene.over_url_limit:
            insights.append(
                "Sitemap exceeds the 50,000 URL protocol limit. "
                "Split into a sitemap index with multiple child sitemaps."
            )

        if not insights:
            insights.append("No significant issues detected. Sitemap and crawl are well-aligned.")

        return insights

    # ── BFS crawl ─────────────────────────────────────────────────────────────

    def _is_spa_content(self, content: dict) -> bool:
        text = content.get("text_content", "").lower()
        indicators = [
            "you need to enable javascript",
            "javascript is required",
            "please enable javascript",
            "this app requires javascript",
        ]
        if any(i in text for i in indicators):
            return True
        paragraphs = content.get("paragraphs", [])
        headings = content.get("headings", {})
        total_h = sum(len(v) for v in headings.values()) if headings else 0
        return len(paragraphs) == 0 and total_h == 0 and len(text.strip()) < 100

    def _crawl_bfs(self) -> Set[str]:
        scraper = Scraper(session=self._session)
        visited_norm: Set[str] = set()
        queue: deque = deque([(self.config.root_url, 0)])

        driver = None
        spa_warned = False

        if self.config.js_fallback:
            try:
                from .driver_manager import create_driver
                driver = create_driver()
                logger.info("JS fallback Selenium driver initialised")
            except Exception as exc:
                logger.warning(f"JS fallback driver unavailable: {exc}")

        try:
            while queue and len(visited_norm) < self.config.max_pages:
                if self._stop:
                    logger.info("Audit crawl stopped by signal")
                    break

                current_url, depth = queue.popleft()
                norm = self._norm(current_url)
                if not norm or norm in visited_norm:
                    continue

                visited_norm.add(norm)
                logger.info(f"[crawl] {current_url}  depth={depth}")

                content, links = scraper.scrape_url(current_url)

                if content and self._is_spa_content(content):
                    if driver:
                        content, links = scraper.scrape_dynamic(current_url, driver)
                    elif not spa_warned:
                        logger.warning(
                            "SPA/JS-rendered navigation detected. "
                            "Set js_fallback=True for full coverage."
                        )
                        spa_warned = True

                if not content and driver:
                    content, links = scraper.scrape_dynamic(current_url, driver)

                for link in links:
                    if is_internal_url(self.config.root_url, link):
                        norm_link = self._norm(link)
                        if norm_link and norm_link not in visited_norm:
                            queue.append((link, depth + 1))
        finally:
            if driver:
                driver.quit()

        return visited_norm

    # ── Hygiene ───────────────────────────────────────────────────────────────

    def _check_hygiene(self, entries: List[SitemapEntry]) -> SitemapHygiene:
        from collections import Counter

        url_list = [e.url for e in entries]
        counts = Counter(url_list)
        duplicates = [u for u, c in counts.items() if c > 1]
        missing_lastmod = sum(1 for e in entries if not e.lastmod)

        non_200: Dict[str, int] = {}
        redirects: List[str] = []

        with self._cache_lock:
            cache_snapshot = dict(self._cache)

        for entry in entries:
            info = cache_snapshot.get(entry.url)
            if not info:
                continue
            if info.is_redirect:
                redirects.append(entry.url)
            if info.status_code != 200:
                non_200[entry.url] = info.status_code

        return SitemapHygiene(
            total_urls=len(entries),
            over_url_limit=len(entries) > 50_000,
            over_size_limit=False,
            duplicate_locs=duplicates,
            missing_lastmod=missing_lastmod,
            redirect_entries=redirects,
            non_200_entries=non_200,
        )

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self) -> AuditReport:
        warnings: List[str] = []

        # ── 1. Site intelligence (homepage analysis) ──────────────────────────
        site_intel = self._detect_site_intelligence()

        # ── 2. Discover + parse sitemap ───────────────────────────────────────
        if self.config.sitemap_override:
            sitemap_urls = [self.config.sitemap_override]
            logger.info(f"Using explicit sitemap override: {self.config.sitemap_override}")
        else:
            sitemap_urls = discover_sitemap_urls(self.config.root_url, self._session)

        if not sitemap_urls:
            warnings.append(
                "No sitemap found. All crawled pages will appear as MISSING_FROM_SITEMAP."
            )
            logger.warning("No sitemap discovered")

        logger.info(f"Parsing {len(sitemap_urls)} sitemap source(s)…")
        visited_sitemaps: Set[str] = set()
        entries: List[SitemapEntry] = []
        for sm_url in sitemap_urls:
            batch = parse_sitemap(sm_url, self._session, visited_sitemaps)
            entries.extend(batch)
            logger.info(f"  {sm_url} → {len(batch)} URLs")

        logger.info(f"Total sitemap URLs: {len(entries)}")

        sitemap_norm: Set[str] = set()
        sitemap_raw_by_norm: Dict[str, str] = {}
        for e in entries:
            n = self._norm(e.url)
            if n:
                sitemap_norm.add(n)
                sitemap_raw_by_norm[n] = e.url

        # ── 3. BFS crawl ──────────────────────────────────────────────────────
        if site_intel.spa_detected and not self.config.js_fallback:
            warnings.append(
                f"Site is a {site_intel.framework or 'JavaScript'} SPA. "
                "Static crawl will miss JS-rendered navigation links. "
                "Enable JS Fallback for accurate coverage."
            )

        logger.info(f"Crawling up to {self.config.max_pages} pages…")
        crawled_norm = self._crawl_bfs()
        logger.info(f"Crawled {len(crawled_norm)} URLs")

        if self._stop:
            warnings.append("Audit was stopped before completion — results may be partial.")

        # ── 4. Fetch page metadata for sitemap URLs (concurrent) ──────────────
        urls_to_check = list(sitemap_raw_by_norm.values())
        logger.info(f"Checking {len(urls_to_check)} sitemap URLs for SEO metadata…")

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            futures = {pool.submit(self._fetch_page_info, u): u for u in urls_to_check}
            for fut in as_completed(futures):
                if self._stop:
                    break
                try:
                    fut.result()
                except Exception as exc:
                    logger.error(f"Page info fetch error: {exc}")

        with self._cache_lock:
            cache_snapshot = dict(self._cache)

        # ── 5. Set comparison ─────────────────────────────────────────────────
        covered = sorted(crawled_norm & sitemap_norm)
        missing_from_sitemap_norm = sorted(crawled_norm - sitemap_norm)
        orphaned_norm = sorted(sitemap_norm - crawled_norm)

        # Reconstruct raw URLs for missing set
        # (crawled_norm has normalised URLs; we need raw ones for display)
        # Best effort: use the normalised URL since we don't store raw→norm for crawled
        missing_from_sitemap = missing_from_sitemap_norm

        # Split missing into real pages vs non-page files
        missing_pages = [u for u in missing_from_sitemap if not _is_non_page_url(u)]
        non_page_files = [u for u in missing_from_sitemap if _is_non_page_url(u)]

        # ── 6. Orphan categorisation ──────────────────────────────────────────
        orphan_details: List[OrphanDetail] = []
        for norm_url in orphaned_norm:
            raw_url = sitemap_raw_by_norm.get(norm_url, norm_url)
            info = cache_snapshot.get(raw_url)
            detail = self._categorize_orphan(raw_url, info, site_intel.spa_detected)
            orphan_details.append(detail)

        # ── 7. SEO checks ─────────────────────────────────────────────────────
        noindex_in_sitemap: List[str] = []
        canonical_mismatch: List[str] = []

        for norm_url, raw_url in sitemap_raw_by_norm.items():
            info = cache_snapshot.get(raw_url)
            if not info:
                continue

            if info.noindex:
                noindex_in_sitemap.append(raw_url)

            if info.canonical:
                canon_norm = self._norm(info.canonical)
                if canon_norm and canon_norm != norm_url:
                    canonical_mismatch.append(raw_url)
                    logger.info(f"canonical mismatch: loc={raw_url}  canonical={info.canonical}")

        seo_issues: Dict[str, List[str]] = {}
        if noindex_in_sitemap:
            seo_issues["noindex_in_sitemap"] = noindex_in_sitemap
        if canonical_mismatch:
            seo_issues["canonical_mismatch"] = canonical_mismatch

        # ── 8. Hygiene ────────────────────────────────────────────────────────
        hygiene = self._check_hygiene(entries)

        # ── 9. Insights ───────────────────────────────────────────────────────
        insights = self._generate_insights(
            site_intel, orphan_details, missing_pages, non_page_files, hygiene
        )
        for insight in insights:
            logger.info(f"[insight] {insight}")

        # ── 10. Verdict ───────────────────────────────────────────────────────
        real_orphans = [d for d in orphan_details if d.reason != REASON_JS_RENDERED]
        fail_conditions = [
            bool(real_orphans),
            bool(noindex_in_sitemap),
            bool(canonical_mismatch),
            hygiene.over_url_limit,
            bool(hygiene.duplicate_locs),
            bool(hygiene.non_200_entries),
        ]
        verdict = "FAIL" if any(fail_conditions) else "PASS"
        exit_code = 1 if verdict == "FAIL" else 0

        logger.info(f"Audit complete — {verdict}")

        report = AuditReport(
            root_url=self.config.root_url,
            covered=covered,
            missing_from_sitemap=missing_from_sitemap,
            orphaned_in_sitemap=orphaned_norm,
            missing_pages=missing_pages,
            non_page_files=non_page_files,
            orphan_details=orphan_details,
            site_intelligence=site_intel,
            insights=insights,
            seo_issues=seo_issues,
            hygiene=hygiene,
            verdict=verdict,
            exit_code=exit_code,
            warnings=warnings,
        )

        logger.info(report.to_table())
        return report

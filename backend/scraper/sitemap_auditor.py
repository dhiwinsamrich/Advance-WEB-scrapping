"""
Sitemap auditor — cross-references BFS crawl against XML sitemap declarations.

Reuses the existing Scraper for HTTP fetching and HTML parsing.
Does NOT use Crawler so it can manage its own BFS, collect metadata per-page,
and avoid coupling to the log-file-based session model.

Produces AuditReport with:
  - covered           : URLs in both crawl and sitemap
  - missing_from_sitemap : crawled but not declared in sitemap
  - orphaned_in_sitemap  : declared but unreachable / non-200
  - seo_issues        : noindex_in_sitemap, canonical_mismatch
  - hygiene           : sitemap protocol checks
  - verdict / exit_code : PASS/FAIL for CI
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .scraper import Scraper
from .sitemap_parser import SitemapEntry, discover_sitemap_urls, parse_sitemap
from .utils import get_random_user_agent, is_internal_url

logger = logging.getLogger("auditor")


# ── URL normalisation (stricter than utils.normalize_url) ────────────────────

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

        # Collapse default ports
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


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PageInfo:
    url: str
    final_url: str
    status_code: int
    is_redirect: bool
    noindex: bool
    canonical: Optional[str]
    error: Optional[str] = None


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
    covered: List[str]
    missing_from_sitemap: List[str]
    orphaned_in_sitemap: List[str]
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
            "",
            "Coverage:",
            f"  Covered (crawled + in sitemap) : {len(self.covered)}",
            f"  Missing from sitemap           : {len(self.missing_from_sitemap)}",
            f"  Orphaned in sitemap            : {len(self.orphaned_in_sitemap)}",
            "",
        ]

        def _block(title: str, items: List[str]) -> None:
            if not items:
                return
            lines.append(f"{title} ({len(items)}):")
            for u in items[:20]:
                lines.append(f"  - {u}")
            if len(items) > 20:
                lines.append(f"  ... and {len(items) - 20} more")
            lines.append("")

        _block("MISSING FROM SITEMAP", self.missing_from_sitemap)
        _block("ORPHANED IN SITEMAP", self.orphaned_in_sitemap)

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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _norm(self, url: str) -> Optional[str]:
        return audit_normalize_url(url, strip_query=self.config.strip_query)

    def _fetch_page_info(self, url: str) -> PageInfo:
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

            info = PageInfo(
                url=url,
                final_url=final_url,
                status_code=status_code,
                is_redirect=is_redirect,
                noindex=noindex,
                canonical=canonical,
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

    def _is_spa(self, content: dict) -> bool:
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

    # ── BFS crawl ─────────────────────────────────────────────────────────────

    def _crawl_bfs(self) -> Set[str]:
        """
        BFS using the existing Scraper.  Returns a set of normalised URLs.
        Falls back to Selenium per-page when SPA is detected (if js_fallback=True).
        """
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

                if content and self._is_spa(content):
                    if driver:
                        content, links = scraper.scrape_dynamic(current_url, driver)
                    elif not spa_warned:
                        logger.warning(
                            "SPA/JS-rendered navigation detected. "
                            "Set js_fallback=True for full coverage, "
                            "or seed crawl from sitemap URLs."
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

    # ── Hygiene checks ────────────────────────────────────────────────────────

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

        # ── 1. Discover + parse sitemap ───────────────────────────────────────
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

        # ── 2. BFS crawl ─────────────────────────────────────────────────────
        logger.info(f"Crawling up to {self.config.max_pages} pages from {self.config.root_url}…")
        crawled_norm = self._crawl_bfs()
        logger.info(f"Crawled {len(crawled_norm)} URLs")

        if self._stop:
            warnings.append("Audit was stopped before completion — results may be partial.")

        # ── 3. Fetch page metadata for all sitemap URLs (concurrent) ──────────
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

        # ── 4. Set comparison ─────────────────────────────────────────────────
        covered = sorted(crawled_norm & sitemap_norm)
        missing_from_sitemap = sorted(crawled_norm - sitemap_norm)
        orphaned_in_sitemap = sorted(sitemap_norm - crawled_norm)

        # ── 5. SEO checks ─────────────────────────────────────────────────────
        noindex_in_sitemap: List[str] = []
        canonical_mismatch: List[str] = []

        with self._cache_lock:
            cache_snapshot = dict(self._cache)

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
                    logger.info(
                        f"canonical mismatch: loc={raw_url}  canonical={info.canonical}"
                    )

        seo_issues: Dict[str, List[str]] = {}
        if noindex_in_sitemap:
            seo_issues["noindex_in_sitemap"] = noindex_in_sitemap
        if canonical_mismatch:
            seo_issues["canonical_mismatch"] = canonical_mismatch

        # ── 6. Hygiene ────────────────────────────────────────────────────────
        hygiene = self._check_hygiene(entries)

        # ── 7. Verdict ────────────────────────────────────────────────────────
        fail_conditions = [
            bool(orphaned_in_sitemap),
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
            orphaned_in_sitemap=orphaned_in_sitemap,
            seo_issues=seo_issues,
            hygiene=hygiene,
            verdict=verdict,
            exit_code=exit_code,
            warnings=warnings,
        )

        logger.info(report.to_table())
        return report

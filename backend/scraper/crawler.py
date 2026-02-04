import logging
import time
from collections import deque
from .config import Config
from .scraper import Scraper
from .driver_manager import create_driver
from .logger import get_logger
from .utils import normalize_url, is_internal_url

logger = get_logger("crawler")
scraper_logger = get_logger("scraper")
err_logger = get_logger("errors")

class Crawler:
    def __init__(self, base_url=None, max_depth=None):
        self.base_url = base_url or Config.BASE_URL
        self.max_depth = max_depth if max_depth is not None else Config.MAX_DEPTH
        self.visited = set()
        self.queue = deque([(self.base_url, 0)]) # (url, depth)
        self._stop_event = False
        
        # Initialize components
        # We share one driver instance for the lifecycle of the crawler if needed
        # Or create it on demand. For efficiency in recursive crawls, keeping it open is better.
        self.driver = None 
        if Config.HEADLESS_MODE or True: # Force init of driver if we expect dynamic pages
             # Or we can lazy load it in Scraper. Let's manage it here to close it properly.
             try:
                 self.driver = create_driver()
             except Exception as e:
                 err_logger.critical(f"Could not initialize driver: {e}")
                 # Continue? Maybe static only.
                 pass
        
        self.scraper = Scraper(driver_manager=None)

    def stop(self):
        """Signals the crawler to stop processing the queue."""
        self._stop_event = True

    def _content_needs_javascript(self, content):
        """
        Detect if the scraped content suggests JavaScript is required.
        Returns True if dynamic scraping should be used.
        """
        if not content:
            return False
        
        # Check text content for common JS-required indicators
        text_content = content.get("text_content", "").lower()
        indicators = [
            "you need to enable javascript",
            "javascript is required",
            "please enable javascript",
            "this app requires javascript",
            "javascript to run this app",
            "enable javascript to view",
            "javascript must be enabled",
        ]
        
        for indicator in indicators:
            if indicator in text_content:
                logger.info(f"Detected JS-required indicator: '{indicator}'")
                return True
        
        # Also check if content is suspiciously empty (common in SPAs)
        paragraphs = content.get("paragraphs", [])
        headings = content.get("headings", {})
        total_headings = sum(len(h) for h in headings.values()) if headings else 0
        
        if len(paragraphs) == 0 and total_headings == 0 and len(text_content.strip()) < 100:
            logger.info("Detected minimal content - likely a JS-rendered page")
            return True
        
        return False

    def start(self):
        logger.info(f"Starting crawl on {self.base_url} with max_depth={self.max_depth}")
        
        try:
            while self.queue:
                if self._stop_event:
                    logger.info("Crawl stopping due to stop signal.")
                    break

                current_url, depth = self.queue.popleft()
                
                normalized = normalize_url(current_url)
                if not normalized:
                    continue
                    
                if normalized in self.visited:
                    continue
                
                if depth > self.max_depth:
                    continue
                
                self.visited.add(normalized)
                
                logger.info(f"Processing: {current_url} (Depth: {depth})")
                
                # Choose strategy: Simple logic for now, standard scrape.
                # If we had a way to detect dynamic requirement beforehand, we'd pass use_driver=True
                # For now, let's assume we use the driver if the scraper falls back, 
                # OR we just pass the driver always if we want to be safe (but slower).
                # Optimization: Try static first (Scraper default), only use driver if needed.
                # The Scraper class currently has methods `scrape_url` (static) and `scrape_dynamic`.
                # Let's try static first.
                
                content, links = self.scraper.scrape_url(current_url)
                
                # If static failed, returned empty, or content indicates JS is required, try dynamic
                needs_js = self._content_needs_javascript(content)
                if (not content or needs_js) and self.driver:
                    logger.info(f"Retrying with Selenium: {current_url}")
                    content, links = self.scraper.scrape_dynamic(current_url, self.driver)

                if content:
                    # Log extracted content
                    scraper_logger.info("Extracted content", extra={
                        "url": current_url,
                        "depth": depth,
                        "title": content.get("title"),
                        "data": content # Full structured data
                    })
                    
                    # Queue links
                    if depth < self.max_depth:
                        for link in links:
                            if is_internal_url(self.base_url, link):
                                norm_link = normalize_url(link)
                                if norm_link and norm_link not in self.visited:
                                    self.queue.append((link, depth + 1))
                else:
                    scraper_logger.warning(f"No content extracted for {current_url}", extra={"url": current_url})
                    err_logger.warning(f"No content extracted for {current_url}")

        except KeyboardInterrupt:
            logger.info("Crawl interrupted by user.")
        except Exception as e:
            err_logger.error(f"Critical crawler error: {e}")
        finally:
            self.cleanup()
            
    def cleanup(self):
        if self.driver:
            logger.info("Closing WebDriver...")
            self.driver.quit()
        logger.info("Crawl finished.")

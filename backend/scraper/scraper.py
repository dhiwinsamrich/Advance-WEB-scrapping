import time
import requests
import logging
from dataclasses import asdict
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .config import Config
from .utils import get_random_user_agent
from .parser import parse_html, ExtractedContent
from .logger import get_logger

logger = get_logger("scraper")
error_logger = get_logger("errors")

class Scraper:
    def __init__(self, driver_manager=None):
        self.session = requests.Session()
        self.driver = None 
        # driver is passed/managed by Crawler usually, or we init here if needed.
        # For session reuse, we'll accept an existing driver instance.

        self.session.headers.update({
            "User-Agent": get_random_user_agent(),
            "Accept-Language": "en-US,en;q=0.9",
        })

    def scrape_url(self, url, driver=None):
        """
        Extract content from URL.
        Strategy:
        1. Try Requests first (faster).
        2. Detect if content seems missing or if JS is required (heuristic).
        3. If dynamic, use Selenium.
        For now, we can config to Force Selenium or use a simple heuristic.
        """
        
        # Random delay before request
        time.sleep(Config.MIN_DELAY) 

        try:
            # Attempt Static Scrape
            logger.info(f"Scraping static: {url}")
            response = self.session.get(url, timeout=Config.PAGE_LOAD_TIMEOUT)
            
            if response.status_code == 403:
                error_logger.warning(f"403 Forbidden on {url}. Possible bot protection.")
                # Could try Selenium here as fallback if 403 was due to headers/cookies
            
            if response.status_code != 200:
                error_logger.error(f"Failed to fetch {url}: Status {response.status_code}")
                return None, []

            html = response.text
            
            # Simple Heuristic: If we need Selenium, use it. 
            # (e.g., empty body or specific markers). 
            # For this MVP, we'll try to stick to static unless configured otherwise or obvious failure.
            
            # Parse
            content = parse_html(html, url)
            
            return asdict(content), content.links

        except Exception as e:
            error_logger.exception(f"Error scraping {url}: {e}")
            return None, []

    def scrape_dynamic(self, url, driver):
        """
        Scrape using Selenium Driver.
        """
        if not driver:
            error_logger.error("Selenium driver not provided for dynamic scrape.")
            return None, []
            
        try:
            logger.info(f"Scraping dynamic: {url}")
            driver.get(url)
            
            # Wait for body
            WebDriverWait(driver, Config.PAGE_LOAD_TIMEOUT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Auto-scroll to trigger lazy loading
            self.auto_scroll(driver)
            
            html = driver.page_source
            content = parse_html(html, url)
            return asdict(content), content.links
            
        except TimeoutException:
            error_logger.error(f"Timeout waiting for page load: {url}")
            return None, []
        except Exception as e:
            error_logger.exception(f"Selenium error on {url}: {e}")
            return None, []

    def auto_scroll(self, driver):
        """
        Scroll down the page to trigger lazy loading.
        """
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1) # Wait to load
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

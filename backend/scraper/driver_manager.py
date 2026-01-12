import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from .config import Config
from .utils import get_random_user_agent

logger = logging.getLogger("crawler")

def create_driver(headless=None):
    if headless is None:
        headless = Config.HEADLESS_MODE
        
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless")
        
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument(f"user-agent={get_random_user_agent()}")
    
    # Anti-detection (Basic)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # Set timeouts
        driver.set_page_load_timeout(Config.PAGE_LOAD_TIMEOUT)
        driver.set_script_timeout(Config.SCRIPT_TIMEOUT)
        driver.implicitly_wait(Config.IMPLICIT_WAIT)
        
        return driver
    except Exception as e:
        logger.error(f"Failed to create driver: {e}")
        raise

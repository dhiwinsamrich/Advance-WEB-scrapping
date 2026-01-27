import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

class Config:
    BASE_URL = os.getenv("BASE_URL", "https://books.toscrape.com/")
    MAX_DEPTH = int(os.getenv("MAX_DEPTH", 2))
    
    HEADLESS_MODE = os.getenv("HEADLESS_MODE", "True").lower() in ("true", "1", "t")
    
    # Timeouts
    PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", 60))
    SCRIPT_TIMEOUT = int(os.getenv("SCRIPT_TIMEOUT", 60))
    IMPLICIT_WAIT = int(os.getenv("IMPLICIT_WAIT", 15))
    
    # Logging
    LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    
    # Random Delays (min, max) in seconds
    MIN_DELAY = 1.0
    MAX_DELAY = 3.0

    @classmethod
    def validate(cls):
        if not cls.BASE_URL:
            raise ValueError("BASE_URL must be set in .env or config")

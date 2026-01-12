from scraper.config import Config
from scraper.crawler import Crawler
from scraper.logger import get_logger

logger = get_logger("crawler")

def main():
    try:
        Config.validate()
        logger.info("Configuration validated.")
        
        crawler = Crawler()
        crawler.start()
        
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        exit(1)

if __name__ == "__main__":
    main()

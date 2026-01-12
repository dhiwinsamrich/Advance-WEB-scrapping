import random
from urllib.parse import urlparse, urljoin, urlunparse
from fake_useragent import UserAgent

ua = UserAgent()

def get_random_user_agent():
    try:
        return ua.random
    except Exception:
        # Fallback if fake-useragent fails
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def normalize_url(url):
    """
    Standardize URL by removing fragments and query parameters (optional),
    and ensuring consistent scheme/netloc.
    """
    if not url:
        return None
    
    parsed = urlparse(url)
    
    # Normalize scheme to lower
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    
    if not scheme or not netloc:
        return None # Invalid URL
    
    # Strip fragment
    return urlunparse((scheme, netloc, parsed.path, parsed.params, parsed.query, ''))

def is_internal_url(base_url, target_url):
    """
    Check if target_url belongs to the same domain as base_url.
    """
    base_domain = urlparse(base_url).netloc
    target_domain = urlparse(target_url).netloc
    
    return base_domain == target_domain or target_domain.endswith("." + base_domain)

def resolve_url(base_url, link):
    """
    Handle relative links.
    """
    return urljoin(base_url, link)

from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from .utils import resolve_url

@dataclass
class ExtractedContent:
    title: str
    meta_description: str
    headings: Dict[str, List[str]]
    paragraphs: List[str]
    links: List[str] # All links found
    images: List[Dict[str, str]] # list of {src, alt}
    forms: List[Dict[str, str]] # Simple form structure representation
    text_content: str # raw text dump

def parse_html(html_content: str, base_url: str) -> ExtractedContent:
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Title & Meta
    title = soup.title.string.strip() if soup.title else ""
    meta_desc = ""
    meta_tag = soup.find('meta', attrs={'name': 'description'})
    if meta_tag:
        meta_desc = meta_tag.get('content', '').strip()

    # 2. Headings
    headings = {}
    for level in range(1, 7):
        tag = f'h{level}'
        headings[tag] = [h.get_text(strip=True) for h in soup.find_all(tag)]

    # 3. Paragraphs
    paragraphs = [p.get_text(strip=True) for p in soup.find_all('p') if p.get_text(strip=True)]

    # 4. Links
    links = []
    for a in soup.find_all('a', href=True):
        full_url = resolve_url(base_url, a['href'])
        links.append(full_url)
    
    # 5. Images
    images = []
    for img in soup.find_all('img', src=True):
        img_src = resolve_url(base_url, img['src'])
        images.append({
            "src": img_src,
            "alt": img.get('alt', '')
        })

    # 6. Forms (Basic capture)
    forms = []
    for form in soup.find_all('form'):
        form_data = {
            "action": form.get('action', ''),
            "method": form.get('method', 'get'),
            "inputs": []
        }
        for inp in form.find_all('input'):
            form_data["inputs"].append({
                "name": inp.get('name'),
                "type": inp.get('type'),
                "placeholder": inp.get('placeholder')
            })
        forms.append(form_data)
        
    # 7. Main Text Content (Structured blocks - simplified for log)
    # Get text from generic containers like article, section, div.main
    main_content = soup.get_text(separator='\n', strip=True)

    return ExtractedContent(
        title=title,
        meta_description=meta_desc,
        headings=headings,
        paragraphs=paragraphs,
        links=list(set(links)), # dedupe
        images=images,
        forms=forms,
        text_content=main_content[:5000] # Truncate for sanity if needed, or keep full
    )

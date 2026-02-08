"""
Citation Parser

Extracts citation information from AI response sources.
Determines domain category (Owned/Others) and citation pill status.
"""
from urllib.parse import urlparse
from typing import List, Dict, Optional


def extract_domain(url: str) -> str:
    """
    从 URL 提取 domain。
    
    Examples:
        https://www.eufy.com/products -> eufy.com
        https://example.com/page -> example.com
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def parse_citations(
    sources: Optional[List[Dict]],
    citation_pills: Optional[List[Dict]],
    owned_domains: Optional[List[str]]
) -> List[Dict]:
    """
    从 response_sources 提取 citations。
    
    Args:
        sources: Cloro 返回的 sources 数组
        citation_pills: Cloro 返回的 citationPills 数组
        owned_domains: 客户拥有的域名列表
        
    Returns:
        List of citation dicts
    """
    if not sources:
        return []
    
    # Build set of pill URLs for quick lookup
    pills_urls = set()
    if citation_pills:
        for pill in citation_pills:
            url = pill.get("url", "")
            if url:
                pills_urls.add(url)
    
    # Build set of owned domains (lowercase for comparison)
    owned_set = set()
    if owned_domains:
        for d in owned_domains:
            if d:
                owned_set.add(d.lower())
    
    citations = []
    for source in sources:
        url = source.get("url", "")
        if not url:
            continue
        
        domain = extract_domain(url)
        domain_lower = domain.lower()
        
        citations.append({
            "source_url": url,
            "source_domain": domain,
            "source_position": source.get("position"),
            "source_label": source.get("label"),
            "domain_category": "Owned" if domain_lower in owned_set else "Others",
            "is_citation_pill": url in pills_urls,
        })
    
    return citations

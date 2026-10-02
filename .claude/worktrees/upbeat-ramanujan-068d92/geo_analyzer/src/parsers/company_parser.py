"""
Company Mention Parser

Extracts company name mentions from AI response text.
Uses regex to find known client and peer names.
"""
import re
from typing import List, Dict


def parse_company_mentions(
    text: str,
    client_name: str,
    peers: List[str]
) -> List[Dict]:
    """
    从 response_text 中提取公司提及。
    
    Args:
        text: AI 返回的文本内容
        client_name: 客户名称
        peers: 竞争对手名称列表
        
    Returns:
        List of mention dicts with company_name, mention_position, is_client, is_peer
    """
    if not text:
        return []
    
    mentions = []
    all_companies = []
    
    # Add client if exists
    if client_name:
        all_companies.append(client_name)
    
    # Add peers
    if peers:
        all_companies.extend(peers)
    
    peers_lower = {p.lower() for p in (peers or [])}
    client_lower = client_name.lower() if client_name else ""
    
    for company in all_companies:
        if not company:
            continue
            
        # Case-insensitive, word boundary matching
        # Handle special characters in company names
        pattern = rf'\b{re.escape(company)}\b'
        
        for match in re.finditer(pattern, text, re.IGNORECASE):
            mentions.append({
                "company_name": company,
                "char_position": match.start(),
                "is_client": company.lower() == client_lower,
                "is_peer": company.lower() in peers_lower,
            })
    
    # Sort by position in text
    mentions.sort(key=lambda x: x["char_position"])
    
    # Assign mention_position (1-indexed order of appearance)
    for i, m in enumerate(mentions):
        m["mention_position"] = i + 1
        del m["char_position"]  # Remove temporary field
    
    return mentions

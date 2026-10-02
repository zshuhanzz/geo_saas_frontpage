from typing import Dict, Any
from .base import BaseUnpacker

class ChatGPTUnpacker(BaseUnpacker):
    def unpack(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        response = full_response.get("response", {})
        result = response.get("result", {}) # ChatGPT wrapper usually has 'result' inside 'response'
        # Fallback: if 'result' is missing but fields are at top level (depends on actual payload structure),
        # check provided samples.
        # Sample:
        # "response": {
        #   "success": true,
        #   "result": { "text": ... }
        # }
        # OR Cloro generic response:
        # "response": { "text": ... } 
        # Wait, the sample says:
        # "response": { "text": ... } for TOP LEVEL example.
        # BUT specific platform examples show:
        # "chatgpt": { "success": true, "result": { ... } }
        # The Cloro Envelope "response" field MIGHT contain the inner platform payload.
        # Let's assume the 'cloro_response' passed here is the INNER 'response' part of the main envelope,
        # OR the full envelope.
        # The Worker passes `message_data['response']` usually.
        # Let's handle both "direct fields" and "nested result" just in case.
        
        data = result if result else response

        return {
            "text": data.get("text"),
            "html": data.get("html"),
            "markdown": data.get("markdown"),
            "sources": data.get("sources"),
            "shopping_cards": data.get("shoppingCards"), # CamelCase mapping
            "places": data.get("map"),                   # Map -> Places mapping
            "entities": data.get("entities"),
            "search_queries": data.get("searchQueries"),
            "citation_pills": data.get("citationPills")
        }

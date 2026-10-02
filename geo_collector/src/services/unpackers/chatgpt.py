from typing import Any, Dict

from .base import BaseUnpacker


class ChatGPTUnpacker(BaseUnpacker):
    def unpack(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        data = self._result(full_response)

        return {
            "text": self._optional_string(data.get("text")),
            "html": self._optional_string(data.get("html")),
            "markdown": self._optional_string(data.get("markdown")),
            "sources": self._normalize_sources(data.get("sources")),
            "shopping_cards": self._safe_list(data.get("shoppingCards")),
            "places": self._safe_list(data.get("map")),
            "entities": data.get("entities") if isinstance(data.get("entities"), dict) else None,
            "search_queries": self._safe_list(data.get("searchQueries"), (str, dict)),
            "citation_pills": self._normalize_citation_pills(data.get("citationPills")),
        }

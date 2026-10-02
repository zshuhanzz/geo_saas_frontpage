from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseUnpacker(ABC):
    """
    Abstract base class for platform-specific response unpackers.
    Responsible for extracting standardized fields from the raw Cloro JSON response.
    """

    @abstractmethod
    def unpack(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Unpack the raw response into a flat dictionary of fields for the geo_results table.
        
        Args:
            full_response: The full JSON envelope from Cloro (containing 'task', 'response', etc.)
            
        Returns:
            Dict containing keys matching geo_results columns:
            - text, html, markdown
            - sources, shopping_cards, places, entities
            - search_queries, citation_pills
        """
        pass

    def _safe_get(self, data: Dict, key: str, default=None):
        return data.get(key, default)

    def _response(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(full_response, dict):
            return {}
        response = full_response.get("response", full_response)
        return response if isinstance(response, dict) else {}

    def _result(self, full_response: Dict[str, Any]) -> Dict[str, Any]:
        response = self._response(full_response)
        result = response.get("result")
        return result if isinstance(result, dict) and result else response

    def _first(self, data: Dict[str, Any], *keys: str, default=None):
        for key in keys:
            value = data.get(key)
            if value is not None:
                return value
        return default

    def _optional_string(self, value: Any):
        return value if isinstance(value, str) else None

    def _safe_list(self, value: Any, item_types=None):
        if not isinstance(value, list):
            return []
        if item_types is None:
            return list(value)
        return [item for item in value if isinstance(item, item_types)]

    def _normalize_sources(self, sources):
        if not isinstance(sources, list):
            return []

        normalized = []
        for item in sources:
            if not isinstance(item, dict):
                continue
            normalized.append({
                **item,
                "url": item.get("url") or item.get("link"),
                "label": item.get("label") or item.get("title") or item.get("domain"),
                "description": item.get("description") or item.get("snippet"),
            })
        return normalized

    def _normalize_citation_pills(self, citation_pills):
        if not isinstance(citation_pills, list):
            return []

        normalized = []
        for item in citation_pills:
            if not isinstance(item, dict):
                continue
            normalized.append({
                **item,
                "url": item.get("url") or item.get("link"),
            })
        return normalized

    def _citations_to_pills(self, citations, sources):
        if not isinstance(citations, list) or not isinstance(sources, list):
            return None

        pills = []
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            source_indexes = citation.get("sourceIndexes") or citation.get("source_indices") or []
            if not isinstance(source_indexes, list):
                source_indexes = []
            for source_index in source_indexes:
                if not isinstance(source_index, int):
                    continue
                source = sources[source_index - 1] if 0 < source_index <= len(sources) else {}
                if not isinstance(source, dict):
                    source = {}
                pills.append({
                    "label": citation.get("label"),
                    "sourceIndexes": source_indexes,
                    "sourceIndex": source_index,
                    "url": source.get("url") or source.get("link"),
                })
        return pills

from abc import ABC, abstractmethod
from typing import Dict, Any

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

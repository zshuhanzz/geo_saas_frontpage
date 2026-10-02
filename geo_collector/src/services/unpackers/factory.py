from typing import Dict, Type
from .base import BaseUnpacker
from .chatgpt import ChatGPTUnpacker
from .gemini import GeminiUnpacker
from .aimode import AIModeUnpacker
from .perplexity import PerplexityUnpacker
from .aioverview import AIOverviewUnpacker

class UnpackerFactory:
    _strategies: Dict[str, Type[BaseUnpacker]] = {
        "chatgpt": ChatGPTUnpacker,
        "gemini": GeminiUnpacker,
        "aimode": AIModeUnpacker,
        "perplexity": PerplexityUnpacker,
        "aioverview": AIOverviewUnpacker,
        "ai_overview": AIOverviewUnpacker,
        "google_ai_overview": AIOverviewUnpacker,
    }

    @classmethod
    def get_unpacker(cls, platform: str) -> BaseUnpacker:
        """
        Get the appropriate unpacker instance for the given platform.
        Defaults to ChatGPTUnpacker if platform is unknown.
        """
        key = platform.lower().replace(" ", "_").replace("-", "_")
        unpacker_class = cls._strategies.get(key)
        if not unpacker_class:
            # Default to ChatGPT or log warning? For now safe default.
            return ChatGPTUnpacker()
        return unpacker_class()

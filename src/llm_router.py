import logging
import os
from dotenv import load_dotenv

from src import language

load_dotenv()

logger = logging.getLogger("vaani.llm_router")


class LLMRouter:
    """
    Automatic LLM failover chain.
    Groq Key 1 → Groq Key 2 → Gemini Flash
    Switches silently when rate limit (429) is hit.
    """

    def __init__(self):
        self.current_index = 0
        self.providers = self._build_providers()
        logger.info(f"LLM Router initialized with {len(self.providers)} providers")
        for i, p in enumerate(self.providers):
            logger.info(f"  Provider {i+1}: {p['name']}")

    def build_livekit_llm_secondary(self):
        """Build LLM using second provider specifically for conversation."""
        if len(self.providers) > 1:
            provider = self.providers[1]
        else:
            provider = self.providers[0]
        logger.info(f"Conversation LLM: {provider['name']}")
        return self._build_from_provider(provider)
    
    def build_livekit_llm_for_language(self, language: str):
        """
        Telugu/Kannada → Qwen2.5-32B on Groq Key 1
        All others → llama-3.1-8b-instant alternating Key 1 and Key 2
        to distribute TPM load across both accounts.
        """
        import os
        from livekit.plugins import groq as groq_plugin

        key1 = os.getenv("GROQ_API_KEY")
        key2 = os.getenv("GROQ_API_KEY_2")

        if language in ["telugu", "kannada"]:
            os.environ["GROQ_API_KEY"] = key1
            logger.info(f"Language {language} → qwen-qwq-32b")
            return groq_plugin.LLM(model="qwen-qwq-32b")
        else:
            # Alternate between keys to distribute TPM load
            if self.current_index == 0 and key2:
                os.environ["GROQ_API_KEY"] = key2
                logger.info(f"Language {language} → Groq Key 2 llama-3.1-8b-instant")
            else:
                os.environ["GROQ_API_KEY"] = key1
                logger.info(f"Language {language} → Groq Key 1 llama-3.1-8b-instant")
            return groq_plugin.LLM(model="llama-3.1-8b-instant")

    def _build_providers(self) -> list:
        providers = []

        # Groq Key 1
        key1 = os.getenv("GROQ_API_KEY")
        if key1:
            providers.append({
                "name": "Groq-Primary (llama-3.1-8b-instant)",
                "type": "groq",
                "key": key1,
                "model": "llama-3.1-8b-instant",
            })

        # Groq Key 2
        key2 = os.getenv("GROQ_API_KEY_2")
        if key2:
            providers.append({
                "name": "Groq-Secondary (llama-3.1-8b-instant)",
                "type": "groq",
                "key": key2,
                "model": "llama-3.1-8b-instant",
            })

        # Gemini Flash
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            providers.append({
                "name": "Gemini-Flash (gemini-1.5-flash)",
                "type": "gemini",
                "key": gemini_key,
                "model": "gemini-1.5-flash",
            })

        if not providers:
            raise ValueError("No LLM API keys found in .env")

        return providers

    def get_current(self) -> dict:
        """Get current active provider."""
        return self.providers[self.current_index]

    def failover(self) -> dict:
        """Switch to next available provider."""
        old = self.providers[self.current_index]["name"]
        self.current_index = (self.current_index + 1) % len(self.providers)
        new = self.providers[self.current_index]["name"]
        logger.warning(f"LLM Failover: {old} → {new}")
        return self.providers[self.current_index]

    def build_livekit_llm(self):
        """Build the correct LiveKit LLM plugin for current provider."""
        provider = self.get_current()
        return self._build_from_provider(provider)

    def _build_from_provider(self, provider: dict):
        """Build LiveKit LLM instance — plugins must already be imported."""
        if provider["type"] == "groq":
            from livekit.plugins import groq as groq_plugin
            os.environ["GROQ_API_KEY"] = provider["key"]
            return groq_plugin.LLM(model=provider["model"])
        elif provider["type"] == "gemini":
            try:
                from livekit.plugins import google as google_plugin
                return google_plugin.LLM(
                    model=provider["model"],
                    api_key=provider["key"],
                )
            except Exception:
                from livekit.plugins import groq as groq_plugin
                return groq_plugin.LLM(model="llama-3.1-8b-instant")
        else:
            raise ValueError(f"Unknown provider type: {provider['type']}")

    def build_triage_client(self):
        """Build async client for triage extraction."""
        provider = self.get_current()

        if provider["type"] == "groq":
            from groq import AsyncGroq
            return AsyncGroq(api_key=provider["key"]), "groq", provider["model"]

        elif provider["type"] == "gemini":
            # Use openai-compatible Gemini endpoint
            from openai import AsyncOpenAI
            return AsyncOpenAI(
                api_key=provider["key"],
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
            ), "gemini", provider["model"]

        return None, None, None


# Global singleton
_router = None

def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
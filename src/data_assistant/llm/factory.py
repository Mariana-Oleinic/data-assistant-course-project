"""Safe provider selection."""

from data_assistant.config import Settings
from data_assistant.llm.base import LLMProvider
from data_assistant.llm.offline import OfflineProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_mode == "offline":
        return OfflineProvider()

    # Settings validation guarantees both explicit billing consent and a key.
    from data_assistant.llm.openai_provider import OpenAIProvider

    assert settings.openai_api_key is not None
    return OpenAIProvider(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
    )


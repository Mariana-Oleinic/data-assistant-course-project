"""Optional Langfuse client factory with an explicit no-telemetry default."""

from typing import Any

from data_assistant.config import Settings


def create_langfuse_client(settings: Settings) -> Any | None:
    """Return no client unless tracing and both credentials are explicitly enabled."""

    if not settings.langfuse_enabled:
        return None
    try:
        from langfuse import Langfuse
    except ImportError as exc:  # pragma: no cover - optional integration
        raise RuntimeError(
            "Install optional observability support with: pip install -e '.[observability]'"
        ) from exc

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_base_url,
        environment=settings.langfuse_tracing_environment,
    )

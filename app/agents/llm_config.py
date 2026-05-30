import os

from agno.models.openai import OpenAIChat
from django.conf import settings

DEFAULT_OPENAI_MODEL = os.getenv("DEFAULT_OPENAI_MODEL", "gpt-4o-mini")


class LLMConfigError(RuntimeError):
    """Erro de configuracao para uso da LLM."""


def get_openai_model_id() -> str:
    model_id = (
        getattr(settings, "OPENAI_MODEL", "")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_OPENAI_MODEL
    ).strip().strip('"').strip("'")
    if not model_id:
        raise LLMConfigError("OPENAI_MODEL invalido.")
    return model_id


def get_openai_api_key() -> str:
    api_key = (
        getattr(settings, "OPENAI_API_KEY", "")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip().strip('"').strip("'")
    if not api_key:
        raise LLMConfigError("OPENAI_API_KEY nao configurada.")
    return api_key


def build_openai_chat_model() -> OpenAIChat:
    return OpenAIChat(
        id=get_openai_model_id(),
        api_key=get_openai_api_key(),
    )

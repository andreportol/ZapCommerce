from agno.agent import Agent

from .llm_config import LLMConfigError, build_openai_chat_model


class AgentExecutionError(RuntimeError):
    """Erro ao executar agente."""


def create_base_agent(name: str, instructions: str) -> Agent:
    return Agent(
        name=name,
        model=build_openai_chat_model(),
        instructions=instructions,
        markdown=False,
    )


def run_text(agent: Agent, message: str) -> str:
    if not message or not message.strip():
        raise ValueError("Mensagem vazia.")

    try:
        result = agent.run(message.strip())
        content = getattr(result, "content", "")
        return str(content or "").strip()
    except LLMConfigError:
        raise
    except Exception as exc:
        raise AgentExecutionError(f"Falha ao executar agente: {exc}") from exc

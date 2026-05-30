from .base_agent import AgentExecutionError, create_base_agent, run_text
from .llm_config import LLMConfigError

TEST_AGENT_NAME = "AgenteTesteIntegracao"
TEST_AGENT_INSTRUCTIONS = (
    "Voce e um agente de teste de integracao. "
    "Responda de forma curta e direta."
)


def create_test_agent():
    return create_base_agent(
        name=TEST_AGENT_NAME,
        instructions=TEST_AGENT_INSTRUCTIONS,
    )


def enviar_mensagem_teste_llm(message: str) -> str:
    try:
        agent = create_test_agent()
        return run_text(agent=agent, message=message)
    except LLMConfigError as exc:
        return f"Erro de configuracao LLM: {exc}"
    except AgentExecutionError as exc:
        return f"Erro na chamada da LLM: {exc}"

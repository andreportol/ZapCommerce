import os
from dataclasses import dataclass

from .base_agent import create_base_agent, run_text
from .llm_config import LLMConfigError


@dataclass
class MessageAnalysis:
    intent: str
    original_message: str
    menu_option: str = ""


class MessageAgent:
    """Analisa mensagem e identifica intencao principal."""

    def __init__(self) -> None:
        self.use_llm_intent = (os.getenv("USE_LLM_INTENT", "false").strip().lower() == "true")
        self._agent = None
        if self.use_llm_intent:
            try:
                self._agent = create_base_agent(
                    name="MessageAgent",
                    instructions=(
                        "Classifique a intencao principal da mensagem do usuario em uma das opcoes: "
                        "consultar pedido, consultar pagamento, duvida geral, envio de comprovante, atendimento humano. "
                        "Responda apenas com a intencao."
                    ),
                )
            except LLMConfigError:
                self._agent = None

    def analyze(self, message: str) -> MessageAnalysis:
        message = (message or "").strip()
        if not message:
            return MessageAnalysis(intent="duvida geral", original_message="", menu_option="")

        menu_option = self._extract_menu_option(message)
        if menu_option:
            return MessageAnalysis(intent=f"menu_opcao_{menu_option}", original_message=message, menu_option=menu_option)

        intent = self._classify_with_rules(message)
        if self._agent is not None:
            try:
                llm_intent = run_text(self._agent, message).strip().lower()
                if llm_intent in {
                    "consultar pedido",
                    "consultar pagamento",
                    "duvida geral",
                    "envio de comprovante",
                    "atendimento humano",
                }:
                    intent = llm_intent
            except Exception:
                pass
        return MessageAnalysis(intent=intent, original_message=message, menu_option="")

    def _extract_menu_option(self, message: str) -> str:
        normalized = message.strip().lower()
        if normalized in {"1", "2", "3", "4"}:
            return normalized
        return ""

    def _classify_with_rules(self, message: str) -> str:
        text = message.lower()
        if any(k in text for k in ["comprovante", "recibo", "anexo", "arquivo"]):
            return "envio de comprovante"
        if any(k in text for k in ["pedido", "status", "entrega"]):
            return "consultar pedido"
        if any(k in text for k in ["pagamento", "pagar", "pix", "cartao", "cartão"]):
            return "consultar pagamento"
        if any(k in text for k in ["atendente", "humano", "pessoa"]):
            return "atendimento humano"
        return "duvida geral"

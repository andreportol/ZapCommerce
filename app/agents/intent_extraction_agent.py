import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from .base_agent import AgentExecutionError, create_base_agent, run_text
from .llm_config import LLMConfigError


ALLOWED_INTENTS = {
    "saudacao",
    "fazer_pedido",
    "consultar_cardapio",
    "consultar_preco",
    "informar_entrega",
    "informar_retirada",
    "informar_endereco",
    "alterar_quantidade",
    "falar_atendente",
    "cancelar_pedido",
    "desconhecida",
}


@dataclass
class IntentExtractionResult:
    intencao: str = "desconhecida"
    produto: str | None = None
    quantidade: int | None = None
    tipo_marmita: str | None = None
    tipo_entrega: str | None = None
    endereco: str | None = None
    forma_pagamento: str | None = None
    observacoes: str | None = None
    mensagem_livre: str | None = None
    confianca: float = 0.0
    precisa_confirmacao: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class IntentExtractionAgent:
    """Extrai dados estruturados da mensagem sem executar regras de negocio."""

    def __init__(self, confidence_threshold: float = 0.55) -> None:
        self.confidence_threshold = confidence_threshold
        self._agent = create_base_agent(
            name="IntentExtractionAgent",
            instructions=(
                "Voce interpreta mensagens de WhatsApp de uma marmitaria e responde apenas JSON valido.\n"
                "Sua tarefa e extrair intencao e dados. Nao confirme pedido, nao salve nada, nao calcule preco, "
                "nao invente cardapio, taxa, disponibilidade ou regra de negocio.\n"
                "Intencoes permitidas: saudacao, fazer_pedido, consultar_cardapio, consultar_preco, "
                "informar_entrega, informar_retirada, informar_endereco, alterar_quantidade, "
                "falar_atendente, cancelar_pedido, desconhecida.\n"
                "Campos obrigatorios no JSON: intencao, produto, quantidade, tipo_marmita, tipo_entrega, "
                "endereco, forma_pagamento, observacoes, mensagem_livre, confianca, precisa_confirmacao.\n"
                "Use null quando um campo nao estiver claro. confianca deve ser numero de 0 a 1.\n"
                "Use precisa_confirmacao=true quando a mensagem estiver ambigua ou depender do estado da conversa."
            ),
        )

    def extract(self, message: str, state_summary: dict | None = None) -> IntentExtractionResult:
        payload = {
            "mensagem_cliente": message or "",
            "estado_conversa": state_summary or {},
        }
        prompt = json.dumps(payload, ensure_ascii=False)
        raw_response = run_text(self._agent, prompt)
        data = self._parse_json(raw_response)
        return self.normalize(data)

    def normalize(self, data: dict[str, Any]) -> IntentExtractionResult:
        intent = str(data.get("intencao") or "desconhecida").strip().lower()
        if intent not in ALLOWED_INTENTS:
            intent = "desconhecida"

        confidence = self._to_float(data.get("confianca"), default=0.0)
        needs_confirmation = bool(data.get("precisa_confirmacao", False))
        if confidence < self.confidence_threshold:
            intent = "desconhecida"
            needs_confirmation = True

        return IntentExtractionResult(
            intencao=intent,
            produto=self._to_optional_str(data.get("produto")),
            quantidade=self._to_optional_int(data.get("quantidade")),
            tipo_marmita=self._to_optional_str(data.get("tipo_marmita")),
            tipo_entrega=self._to_optional_str(data.get("tipo_entrega")),
            endereco=self._to_optional_str(data.get("endereco")),
            forma_pagamento=self._to_optional_str(data.get("forma_pagamento")),
            observacoes=self._to_optional_str(data.get("observacoes")),
            mensagem_livre=self._to_optional_str(data.get("mensagem_livre")),
            confianca=max(0.0, min(1.0, confidence)),
            precisa_confirmacao=needs_confirmation,
        )

    def _parse_json(self, response: str) -> dict:
        text = (response or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        if "{" in text and "}" in text:
            text = text[text.find("{") : text.rfind("}") + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Resposta da LLM nao e um objeto JSON.")
        return parsed

    def _to_optional_str(self, value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _to_optional_int(self, value) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _to_float(self, value, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default


def try_extract_intent_with_llm(
    message: str,
    state_summary: dict | None = None,
    confidence_threshold: float = 0.55,
) -> IntentExtractionResult | None:
    try:
        return IntentExtractionAgent(confidence_threshold=confidence_threshold).extract(
            message=message,
            state_summary=state_summary,
        )
    except (AgentExecutionError, LLMConfigError, ValueError, json.JSONDecodeError):
        return None

import os
from dataclasses import dataclass
import re
import unicodedata

from .intent_extraction_agent import IntentExtractionResult, try_extract_intent_with_llm


@dataclass
class MessageAnalysis:
    intent: str
    original_message: str
    menu_option: str = ""
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

    @property
    def structured(self) -> dict:
        return {
            "intencao": self.intencao,
            "produto": self.produto,
            "quantidade": self.quantidade,
            "tipo_marmita": self.tipo_marmita,
            "tipo_entrega": self.tipo_entrega,
            "endereco": self.endereco,
            "forma_pagamento": self.forma_pagamento,
            "observacoes": self.observacoes,
            "mensagem_livre": self.mensagem_livre,
            "confianca": self.confianca,
            "precisa_confirmacao": self.precisa_confirmacao,
        }


class MessageAgent:
    """Analisa mensagem e identifica intencao principal."""

    def __init__(self) -> None:
        self.use_llm_intent = (os.getenv("USE_LLM_INTENT", "false").strip().lower() == "true")

    def analyze(self, message: str, state_summary: dict | None = None) -> MessageAnalysis:
        message = (message or "").strip()
        if not message:
            return self._build_analysis(
                message="",
                menu_option="",
                extraction=IntentExtractionResult(
                    intencao="desconhecida",
                    confianca=0.0,
                    precisa_confirmacao=True,
                ),
            )

        menu_option = self._extract_menu_option(message, state_summary=state_summary)
        if menu_option:
            return self._build_analysis(
                message=message,
                menu_option=menu_option,
                extraction=self._extract_menu_option_structured(menu_option),
            )

        extraction = None
        if self.use_llm_intent:
            extraction = try_extract_intent_with_llm(
                message=message,
                state_summary=state_summary,
            )
        if extraction is None:
            extraction = self._extract_with_rules(message, state_summary=state_summary)
        return self._build_analysis(message=message, menu_option="", extraction=extraction)

    def _extract_menu_option(self, message: str, state_summary: dict | None = None) -> str:
        normalized = self._normalize_menu_option_text(message)
        if normalized in {"1", "2", "3", "4"}:
            if self._has_pending_order_step(state_summary):
                return ""
            return normalized
        return ""

    def _normalize_menu_option_text(self, text: str) -> str:
        raw = (text or "").strip().lower()
        if not raw:
            return ""

        # O WhatsApp pode entregar caracteres invisiveis ou pontuacao junto da opcao.
        filtered = "".join(
            ch for ch in unicodedata.normalize("NFKC", raw)
            if unicodedata.category(ch) != "Cf"
        )
        return re.sub(r"^[^\w\d]+|[^\w\d]+$", "", filtered).strip()

    def _has_pending_order_step(self, state_summary: dict | None) -> bool:
        if not state_summary:
            return False
        pending_statuses = {
            "fazendo_pedido",
            "aguardando_tipo_entrega",
            "aguardando_confirmacao_item",
            "aguardando_produto",
            "aguardando_pessoas_marmita",
            "aguardando_quantidade",
            "aguardando_endereco",
            "aguardando_nome_cliente",
            "aguardando_pagamento",
            "aguardando_comprovante",
            "aguardando_conferencia_pagamento",
            "aguardando_confirmacao",
            "aguardando_confirmacao_fazer_pedido",
        }
        pending_responses = {
            "tipo_marmita",
            "quantidade",
            "complemento",
            "quantidade_complemento",
            "mais_complementos",
            "tipo_entrega",
            "endereco",
            "nome_cliente",
            "forma_pagamento",
            "confirmacao",
            "confirmacao_item",
            "comprovante",
            "conferencia_pagamento",
            "pessoas_marmita",
        }
        pedido_atual = state_summary.get("pedido_atual") or {}
        return bool(
            state_summary.get("status_atendimento") in pending_statuses
            or state_summary.get("aguardando_resposta") in pending_responses
            or state_summary.get("ultima_intencao") == "fazer_pedido"
            or pedido_atual.get("produto")
            or pedido_atual.get("quantidade")
            or pedido_atual.get("tipo_entrega")
        )

    def _extract_menu_option_structured(self, menu_option: str) -> IntentExtractionResult:
        mapping = {
            "1": "fazer_pedido",
            "2": "consultar_cardapio",
            "4": "falar_atendente",
        }
        intent = mapping.get(menu_option, "desconhecida")
        return IntentExtractionResult(
            intencao=intent,
            confianca=0.95,
            precisa_confirmacao=False,
        )

    def _extract_with_rules(self, message: str, state_summary: dict | None = None) -> IntentExtractionResult:
        normalized = self._normalize(message)
        quantity = self._extract_quantity(normalized)

        if any(term in normalized for term in ["cancelar", "cancela", "cancele"]):
            return IntentExtractionResult(intencao="cancelar_pedido", confianca=0.95, precisa_confirmacao=False)

        if self._looks_like_human_request(normalized):
            return IntentExtractionResult(intencao="falar_atendente", confianca=0.95, precisa_confirmacao=False)

        if self._looks_like_greeting(normalized):
            return IntentExtractionResult(intencao="saudacao", confianca=0.85, precisa_confirmacao=False)

        if self._looks_like_price_question(normalized):
            return IntentExtractionResult(
                intencao="consultar_preco",
                produto=self._extract_product(normalized),
                quantidade=quantity,
                tipo_marmita=self._extract_tipo_marmita(normalized),
                confianca=0.85,
                precisa_confirmacao=False,
            )

        if self._looks_like_cardapio_question(normalized):
            return IntentExtractionResult(
                intencao="consultar_cardapio",
                produto=self._extract_specific_menu_item(normalized),
                mensagem_livre=message,
                confianca=0.86,
                precisa_confirmacao=False,
            )

        if self._looks_like_address(normalized):
            return IntentExtractionResult(
                intencao="informar_endereco",
                tipo_entrega="entrega",
                endereco=self._extract_address(message),
                confianca=0.88,
                precisa_confirmacao=False,
            )

        if self._looks_like_pickup(normalized):
            return IntentExtractionResult(
                intencao="informar_retirada",
                tipo_entrega="retirada",
                confianca=0.9,
                precisa_confirmacao=False,
            )

        if self._looks_like_quantity_change(normalized, state_summary):
            return IntentExtractionResult(
                intencao="alterar_quantidade",
                quantidade=quantity,
                observacoes="Cliente parece corrigir a quantidade do pedido atual.",
                confianca=0.78 if state_summary else 0.62,
                precisa_confirmacao=not bool(state_summary),
            )

        if self._looks_like_order(normalized):
            return IntentExtractionResult(
                intencao="fazer_pedido",
                produto=self._extract_product(normalized),
                quantidade=quantity,
                tipo_marmita=self._extract_tipo_marmita(normalized),
                tipo_entrega="entrega" if self._looks_like_delivery(normalized) else None,
                confianca=0.84,
                precisa_confirmacao=self._extract_product(normalized) is None,
            )

        if self._looks_like_delivery(normalized):
            return IntentExtractionResult(
                intencao="informar_entrega",
                tipo_entrega="entrega",
                confianca=0.8,
                precisa_confirmacao=False,
            )

        return IntentExtractionResult(intencao="desconhecida", confianca=0.3, precisa_confirmacao=True)

    def _classify_with_rules(self, message: str) -> str:
        text = message.lower()
        if any(k in text for k in ["comprovante", "recibo", "anexo", "arquivo"]):
            return "envio de comprovante"
        if any(k in text for k in ["pedido", "status", "entrega"]):
            return "consultar pedido"
        if any(k in text for k in ["pagamento", "pagar", "pix", "cartao", "cartão"]):
            return "consultar pagamento"
        normalized = self._normalize(text)
        if self._looks_like_human_request(normalized):
            return "atendimento humano"
        return "duvida geral"

    def _build_analysis(self, message: str, menu_option: str, extraction: IntentExtractionResult) -> MessageAnalysis:
        legacy_intent = f"menu_opcao_{menu_option}" if menu_option else self._legacy_intent_from_extraction(extraction, message)
        return MessageAnalysis(
            intent=legacy_intent,
            original_message=message,
            menu_option=menu_option,
            intencao=extraction.intencao,
            produto=extraction.produto,
            quantidade=extraction.quantidade,
            tipo_marmita=extraction.tipo_marmita,
            tipo_entrega=extraction.tipo_entrega,
            endereco=extraction.endereco,
            forma_pagamento=extraction.forma_pagamento,
            observacoes=extraction.observacoes,
            mensagem_livre=extraction.mensagem_livre,
            confianca=extraction.confianca,
            precisa_confirmacao=extraction.precisa_confirmacao,
        )

    def _legacy_intent_from_extraction(self, extraction: IntentExtractionResult, message: str) -> str:
        if extraction.intencao == "falar_atendente":
            return "atendimento humano"
        if extraction.intencao == "consultar_preco":
            return "consultar pagamento"
        if extraction.intencao == "informar_entrega":
            return "consultar pedido"
        return self._classify_with_rules(message)

    def _normalize(self, text: str) -> str:
        raw = (text or "").strip().lower()
        raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
        raw = re.sub(r"[^a-z0-9\s]", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()

    def _extract_quantity(self, normalized: str) -> int | None:
        number_words = {
            "um": 1,
            "uma": 1,
            "dois": 2,
            "duas": 2,
            "tres": 3,
            "quatro": 4,
            "cinco": 5,
            "seis": 6,
            "sete": 7,
            "oito": 8,
            "nove": 9,
            "dez": 10,
        }
        for token in normalized.split():
            if token.isdigit():
                return int(token)
            if token in number_words:
                return number_words[token]
        return None

    def _extract_product(self, normalized: str) -> str | None:
        if "marmitex" in normalized:
            return "marmitex"
        if "marmita" in normalized:
            return "marmita"
        if re.search(r"\b\d{1,2}\s+pessoas?\b", normalized):
            return "marmita"
        return self._extract_specific_menu_item(normalized)

    def _extract_specific_menu_item(self, normalized: str) -> str | None:
        known_items = ["feijoada", "frango", "bife", "peixe", "macarrao"]
        for item in known_items:
            if item in normalized:
                return item
        return None

    def _extract_tipo_marmita(self, normalized: str) -> str | None:
        if "individual" in normalized or "marmitex" in normalized:
            return "individual"
        people = re.search(r"\b(\d{1,2})\s+pessoas?\b", normalized)
        if people:
            return f"{people.group(1)}_pessoas"
        return None

    def _extract_address(self, message: str) -> str | None:
        match = re.search(r"\b(?:entrega\s+)?(?:na|no|em)\s+(.+)$", message, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return message.strip() or None

    def _looks_like_greeting(self, normalized: str) -> bool:
        return normalized in {"oi", "ola", "bom dia", "boa tarde", "boa noite", "oi bom dia", "oi boa tarde"}

    def _looks_like_price_question(self, normalized: str) -> bool:
        return any(term in normalized for term in ["quanto", "valor", "preco", "precos", "fica", "custa"])

    def _looks_like_cardapio_question(self, normalized: str) -> bool:
        return any(term in normalized for term in ["cardapio", "menu", "tem ", "tem hoje", "hoje"])

    def _looks_like_address(self, normalized: str) -> bool:
        return any(term in normalized for term in ["rua", "avenida", "av ", "bairro", "travessa", "numero", "cep"])

    def _looks_like_pickup(self, normalized: str) -> bool:
        return any(term in normalized for term in ["retirar", "retirada", "buscar", "vou buscar", "pegar no local"])

    def _looks_like_delivery(self, normalized: str) -> bool:
        return any(term in normalized for term in ["entrega", "entregar", "para entregar"])

    def _looks_like_human_request(self, normalized: str) -> bool:
        return (
            "atendente" in normalized
            or "humano" in normalized
            or "falar com pessoa" in normalized
            or re.search(r"\bpessoa\b", normalized) is not None
        )

    def _looks_like_quantity_change(self, normalized: str, state_summary: dict | None) -> bool:
        has_quantity = self._extract_quantity(normalized) is not None
        correction = any(term in normalized for term in ["na verdade", "corrige", "troca", "muda", "quero"])
        if not has_quantity or not correction:
            return False
        if not state_summary:
            return "na verdade" in normalized
        pedido_atual = state_summary.get("pedido_atual") or {}
        has_active_order_data = bool(
            state_summary.get("ultima_intencao") == "fazer_pedido"
            or state_summary.get("status_atendimento") not in {"", "inicio"}
            or state_summary.get("aguardando_resposta") in {
                "quantidade",
                "complemento",
                "quantidade_complemento",
                "mais_complementos",
                "tipo_entrega",
                "endereco",
                "nome_cliente",
                "forma_pagamento",
            }
            or pedido_atual.get("produto")
            or pedido_atual.get("quantidade")
            or pedido_atual.get("tipo_entrega")
            or pedido_atual.get("endereco")
        )
        return bool(
            has_active_order_data
        )

    def _looks_like_order(self, normalized: str) -> bool:
        has_order_term = any(term in normalized for term in ["quero", "manda", "mandar", "pedido", "pedir", "marmita", "marmitex"])
        return has_order_term and ("marmita" in normalized or "marmitex" in normalized or "pessoas" in normalized)

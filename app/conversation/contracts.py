from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResponseContract:
    success: bool = True
    message: str = ""
    next_state: str = ""
    awaiting_response: str = ""
    intent: str = ""
    order_updated: bool = False
    payment_updated: bool = False
    requires_human: bool = False
    errors: list[str] = field(default_factory=list)
    raw_response: Any = None

    @classmethod
    def from_order_agent_response(cls, response: dict | None) -> "AgentResponseContract":
        payload = response or {}
        state = cls._extract_state_dict(payload.get("state"))
        pricing = payload.get("pricing") or {}
        message = cls._coerce_text(payload.get("response") or payload.get("next_question"))
        errors = cls._collect_errors(payload)
        return cls(
            success=not errors and bool(payload),
            message=message,
            next_state=cls._coerce_text(state.get("status_atendimento")),
            awaiting_response=cls._coerce_text(state.get("aguardando_resposta")),
            intent=cls._coerce_text(payload.get("intent")),
            order_updated=cls._detect_order_updated(state),
            payment_updated=bool(state.get("forma_pagamento")) or cls._coerce_text(state.get("aguardando_resposta")) in {
                "forma_pagamento",
                "comprovante",
                "conferencia_pagamento",
                "confirmacao",
            },
            requires_human=bool(pricing.get("needs_owner")) or cls._coerce_text(state.get("status_atendimento")) == "encaminhar_atendente",
            errors=errors,
            raw_response=payload,
        )

    @classmethod
    def from_orchestrator_response(cls, response: dict | None) -> "AgentResponseContract":
        payload = response or {}
        state = cls._extract_state_dict(payload.get("order_state") or payload.get("state"))
        database = payload.get("database") or {}
        errors = cls._collect_errors(payload)
        if isinstance(database, dict) and database.get("error"):
            errors.append(cls._coerce_text(database.get("error")))
        message = cls._coerce_text(payload.get("final_response") or payload.get("response"))
        next_state = cls._coerce_text(state.get("status_atendimento"))
        awaiting = cls._coerce_text(state.get("aguardando_resposta"))
        return cls(
            success=not errors and bool(payload),
            message=message,
            next_state=next_state,
            awaiting_response=awaiting,
            intent=cls._coerce_text(payload.get("intent")),
            order_updated=cls._detect_order_updated(state),
            payment_updated=bool(state.get("forma_pagamento")) or awaiting in {
                "forma_pagamento",
                "comprovante",
                "conferencia_pagamento",
                "confirmacao",
            },
            requires_human=next_state == "encaminhar_atendente" or cls._coerce_text(payload.get("intent")) in {"atendimento_humano", "falar_atendente"},
            errors=errors,
            raw_response=payload,
        )

    @classmethod
    def from_message_agent_response(cls, response: Any) -> "AgentResponseContract":
        if response is None:
            return cls(success=False, errors=["empty_message_analysis"], raw_response=response)

        structured = getattr(response, "structured", None)
        data = structured if isinstance(structured, dict) else {}
        message = cls._coerce_text(getattr(response, "original_message", ""))
        errors = []
        if cls._coerce_text(getattr(response, "intencao", "")) in {"", "desconhecida"}:
            errors.append("unknown_intent")
        return cls(
            success=not errors,
            message=message,
            next_state="",
            awaiting_response="",
            intent=cls._coerce_text(getattr(response, "intencao", "") or getattr(response, "intent", "")),
            order_updated=bool(data.get("produto") or data.get("quantidade") or data.get("tipo_entrega")),
            payment_updated=bool(data.get("forma_pagamento")),
            requires_human=cls._coerce_text(getattr(response, "intencao", "")) == "falar_atendente",
            errors=errors,
            raw_response=response,
        )

    @staticmethod
    def _coerce_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        return str(value)

    @classmethod
    def _extract_state_dict(cls, state: Any) -> dict[str, Any]:
        if isinstance(state, dict):
            return state
        if state is None:
            return {}
        if hasattr(state, "__dict__"):
            return {
                key: value
                for key, value in vars(state).items()
                if not key.startswith("_")
            }
        return {}

    @classmethod
    def _collect_errors(cls, payload: dict[str, Any]) -> list[str]:
        if not isinstance(payload, dict):
            return ["invalid_payload"]
        errors = payload.get("errors")
        if isinstance(errors, list):
            return [cls._coerce_text(item) for item in errors if cls._coerce_text(item)]
        if payload.get("success") is False:
            return ["explicit_failure"]
        return []

    @staticmethod
    def _detect_order_updated(state: dict[str, Any]) -> bool:
        return bool(
            state.get("itens_pedido")
            or state.get("produto")
            or state.get("quantidade")
            or state.get("valor_total")
            or state.get("tipo_entrega")
            or state.get("endereco")
        )

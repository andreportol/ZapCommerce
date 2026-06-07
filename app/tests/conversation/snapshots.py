from __future__ import annotations

from typing import Any

from app.conversation.contracts import AgentResponseContract
from app.conversation.state_machine import ConversationStateMachine


def build_conversation_snapshot(steps: list[Any]) -> list[dict[str, Any]]:
    state_machine = ConversationStateMachine()
    snapshot: list[dict[str, Any]] = []

    for index, step in enumerate(steps):
        contract = AgentResponseContract.from_orchestrator_response(getattr(step, "raw_result", None))
        expected_next = state_machine.get_expected_next_awaiting_response(
            getattr(step, "before_awaiting_response", ""),
            getattr(step, "user_message", ""),
        )
        state_machine_allowed = (
            expected_next == state_machine.NOT_MAPPED
            or state_machine.is_transition_allowed(
                getattr(step, "before_awaiting_response", ""),
                getattr(step, "user_message", ""),
                getattr(step, "aguardando_resposta", ""),
            )
        )
        snapshot.append(
            {
                "step_index": index,
                "user_message": getattr(step, "user_message", ""),
                "bot_response": getattr(step, "bot_response", ""),
                "before_awaiting_response": getattr(step, "before_awaiting_response", ""),
                "after_awaiting_response": getattr(step, "aguardando_resposta", ""),
                "status_atendimento": getattr(step, "status_atendimento", ""),
                "contract_success": contract.success,
                "contract_intent": contract.intent,
                "contract_next_state": contract.next_state,
                "contract_awaiting_response": contract.awaiting_response,
                "state_machine_expected_next": expected_next,
                "state_machine_allowed": state_machine_allowed,
                "itens_pedido": list(getattr(step, "itens_pedido", []) or []),
                "valor_total": float(getattr(step, "valor_total", 0.0) or 0.0),
                "tipo_entrega": getattr(step, "tipo_entrega", ""),
                "forma_pagamento": getattr(step, "forma_pagamento", ""),
            }
        )
    return snapshot


def format_conversation_snapshot(snapshot: list[dict[str, Any]]) -> str:
    if not snapshot:
        return "Conversation snapshot: <empty>"

    lines = ["Conversation snapshot:"]
    for step in snapshot:
        items = step.get("itens_pedido") or []
        item_summary = ", ".join(
            f"{item.get('quantidade', 0)}x {item.get('produto', '')}".strip()
            for item in items
        ) or "<sem itens>"
        lines.append(
            (
                f"[{step.get('step_index')}] user={step.get('user_message')!r} | "
                f"before={step.get('before_awaiting_response')!r} -> after={step.get('after_awaiting_response')!r} | "
                f"status={step.get('status_atendimento')!r} | "
                f"expected={step.get('state_machine_expected_next')!r} | "
                f"allowed={step.get('state_machine_allowed')!r} | "
                f"total={step.get('valor_total')!r} | "
                f"recebimento={step.get('tipo_entrega')!r} | "
                f"pagamento={step.get('forma_pagamento')!r} | "
                f"itens={item_summary} | "
                f"bot={step.get('bot_response')!r}"
            )
        )
    return "\n".join(lines)

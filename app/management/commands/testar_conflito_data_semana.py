from dataclasses import dataclass, field
from datetime import date
import unicodedata

from django.core.management.base import BaseCommand

from app.agents.conversation_state import AtendimentoStatus
from app.agents.orchestrator_agent import OrchestratorAgent
import app.agents.orchestrator_agent as orchestrator_module
import app.agents.order_agent as order_module


class Command(BaseCommand):
    help = "Valida conflito de dia da semana versus data real do sistema."

    @dataclass
    class _FakeState:
        telefone: str
        status_atendimento: str = AtendimentoStatus.INICIO
        ultima_intencao: str = ""
        itens_pedido: list[dict] = field(default_factory=list)
        itens_pendentes: list[dict] = field(default_factory=list)
        tipo_entrega: str = ""
        produto: str = ""
        quantidade: int = 0
        valor_unitario: float = 0.0
        valor_total: float = 0.0
        endereco: str = ""
        forma_pagamento: str = ""
        aguardando_resposta: str = ""

    def handle(self, *args, **options):
        store: dict[str, Command._FakeState] = {}
        self._mount_fake_runtime(store)
        orchestrator = OrchestratorAgent()
        orchestrator._is_within_business_hours_now = lambda: False
        orchestrator._is_force_open_hours_enabled = lambda: False
        orchestrator.cardapio_agent.get_cardapio = lambda: (
            "## segunda-feira\n"
            "- Feijoada\n- Arroz\n- Farofa\n"
            "## terca-feira\n"
            "- Frango grelhado\n- Arroz\n- Feijao\n"
        )
        # Simula domingo 31/05/2026 para teste deterministico.
        orchestrator_module.timezone.localdate = lambda: date(2026, 5, 31)

        scenarios = [
            {
                "name": "A",
                "phone": "SIM_CONFLITO_1",
                "messages": ["oi", "2"],
                "expect": "confira os cardapios disponiveis da semana",
            },
            {
                "name": "B",
                "phone": "SIM_CONFLITO_2",
                "messages": ["sim, quero o cardápio de terça-feira", "gostei do cardápio. pode reservar que na segunda às 11 eu retiro"],
                "expect": "percebi uma diferenca",
                "expect_state_marker_after_step": {"step": 1, "value": "consultar_cardapio:terca-feira"},
            },
            {
                "name": "C",
                "phone": "SIM_CONFLITO_3",
                "messages": ["sim, quero o cardápio de segunda-feira", "gostei do cardápio. pode reservar que na segunda às 11 eu retiro"],
                "expect": "que bom que gostou",
                "expect_state_marker_after_step": {"step": 1, "value": "consultar_cardapio:segunda-feira"},
            },
            {
                "name": "D",
                "phone": "SIM_CONFLITO_4",
                "messages": ["sim, quero o cardápio de terça-feira", "gostei do cardápio. pode reservar que eu retiro às 11"],
                "expect": "para reservar o cardapio de terca-feira",
                "expect_state_marker_after_step": {"step": 1, "value": "consultar_cardapio:terca-feira"},
            },
            {
                "name": "F",
                "phone": "SIM_CONFLITO_6",
                "messages": ["vcs entregam no meu serviço?"],
                "expect": "fazemos entrega, sim",
            },
            {
                "name": "G",
                "phone": "SIM_CONFLITO_7",
                "messages": ["quero saber se fazem entrega da marmitex?"],
                "expect": "sim, fazemos entrega de marmitex",
                "expect_not": "fora do horario de pedidos",
            },
            {
                "name": "H",
                "phone": "SIM_CONFLITO_8",
                "messages": ["qual horário de entrega?"],
                "expect": "as entregas acontecem das 11h as 13h",
            },
            {
                "name": "I",
                "phone": "SIM_CONFLITO_9",
                "messages": ["posso retirar no local?"],
                "expect": "sim, voce tambem pode retirar no local",
            },
            {
                "name": "J",
                "phone": "SIM_CONFLITO_10",
                "messages": ["quero 2 marmitex para entregar"],
                "expect": "fora do horario de pedidos",
            },
        ]

        self.stdout.write("cenario | resposta_final | status")
        self.stdout.write("-" * 140)
        for scenario in scenarios:
            phone = scenario["phone"]
            store.pop(phone, None)
            last_response = ""
            state_markers_by_step: dict[int, str] = {}
            for idx, message in enumerate(scenario["messages"], start=1):
                result = orchestrator.handle_message(message=message, telefone=phone)
                last_response = (result.get("final_response") or "")
                current_state = store.get(phone)
                state_markers_by_step[idx] = (current_state.ultima_intencao if current_state else "") or ""
            normalized_response = self._normalize(last_response)
            ok = self._normalize(scenario["expect"]) in normalized_response
            if scenario.get("expect_not"):
                ok = ok and self._normalize(scenario["expect_not"]) not in normalized_response
            marker_cfg = scenario.get("expect_state_marker_after_step")
            if marker_cfg:
                step = int(marker_cfg["step"])
                expected_marker = marker_cfg["value"]
                ok = ok and state_markers_by_step.get(step, "") == expected_marker
            self.stdout.write(
                f"{scenario['name']} | {normalized_response} | {'OK' if ok else 'ERRO'}"
            )

    def _mount_fake_runtime(self, store: dict[str, _FakeState]) -> None:
        def _get_or_create_state(phone: str):
            if phone not in store:
                store[phone] = self._FakeState(telefone=phone)
            return store[phone]

        def _update_state(phone: str, **fields):
            state = _get_or_create_state(phone)
            for key, value in fields.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            return state

        def _reset_state(phone: str):
            store[phone] = self._FakeState(telefone=phone)
            return store[phone]

        orchestrator_module.get_or_create_state = _get_or_create_state
        orchestrator_module.update_state = _update_state
        orchestrator_module.reset_state = _reset_state
        order_module.get_or_create_state = _get_or_create_state
        order_module.update_state = _update_state
        order_module.reset_state = _reset_state

    def _normalize(self, text: str) -> str:
        raw = (text or "").strip().lower()
        raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
        return " ".join(raw.split())

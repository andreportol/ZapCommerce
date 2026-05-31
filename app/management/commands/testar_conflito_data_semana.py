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
        )
        # Simula domingo 31/05/2026 para teste deterministico.
        orchestrator_module.timezone.localdate = lambda: date(2026, 5, 31)

        scenarios = [
            {
                "name": "A",
                "phone": "SIM_CONFLITO_1",
                "messages": ["oi", "2", "hoje é segunda-feira"],
                "expect": "pelo sistema, hoje e domingo, 31/05/2026",
            },
            {
                "name": "B",
                "phone": "SIM_CONFLITO_2",
                "messages": ["eu já consigo reservar hoje o cardápio de segunda-feira?"],
                "expect": "hoje nao consigo registrar a encomenda",
            },
            {
                "name": "C",
                "phone": "SIM_CONFLITO_3",
                "messages": ["oi", "2", "sim, de segunda"],
                "expect": "o cardapio de segunda-feira",
            },
            {
                "name": "D",
                "phone": "SIM_CONFLITO_4",
                "messages": ["preste atenção, hoje é segunda-feira, faça meu pedido"],
                "expect": "pelo sistema, hoje e domingo, 31/05/2026",
            },
        ]

        self.stdout.write("cenario | resposta_final | status")
        self.stdout.write("-" * 140)
        for scenario in scenarios:
            phone = scenario["phone"]
            store.pop(phone, None)
            last_response = ""
            for message in scenario["messages"]:
                result = orchestrator.handle_message(message=message, telefone=phone)
                last_response = (result.get("final_response") or "")
            normalized_response = self._normalize(last_response)
            ok = self._normalize(scenario["expect"]) in normalized_response
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

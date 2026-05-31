from dataclasses import dataclass, field

from django.core.management.base import BaseCommand

from app.agents.conversation_state import AtendimentoStatus
from app.agents.message_agent import MessageAgent
from app.agents.order_agent import OrderAgent
import app.agents.order_agent as order_module


class Command(BaseCommand):
    help = "Simula conversas em duas etapas para escolha de tipo de marmita apos pedido ambiguo."

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
        self._fake_store: dict[str, Command._FakeState] = {}
        self._mount_fake_state_store(self._fake_store)
        msg_agent = MessageAgent()
        order_agent = OrderAgent()

        tests = [
            ("A", "quero 2 marmitas para entregar", "individual"),
            ("B", "quero 2 marmitas", "para 3 pessoas"),
            ("C", "manda uma marmita", "a de 4"),
            ("D", "quero uma marmita para retirada", "5 pessoas"),
            ("E", "quero 2 marmitas", "não sei"),
        ]

        self.stdout.write("teste | msg1 | msg2 | estado_final | resposta_final | status")
        self.stdout.write("-" * 220)
        for idx, (label, first, second) in enumerate(tests, start=1):
            phone = f"SIM_TIPO_MARMITA_{idx}"
            self._fake_store.pop(phone, None)

            first_analysis = msg_agent.analyze(first, state_summary=None)
            order_agent.process_message(phone, first, structured_analysis=first_analysis.structured)

            s1 = self._get_state(phone)
            second_state_summary = {
                "status_atendimento": s1.status_atendimento,
                "ultima_intencao": s1.ultima_intencao,
                "aguardando_resposta": s1.aguardando_resposta,
                "pedido_atual": {
                    "produto": s1.produto,
                    "quantidade": s1.quantidade,
                    "tipo_entrega": s1.tipo_entrega,
                    "endereco": s1.endereco,
                    "forma_pagamento": s1.forma_pagamento,
                },
            }
            second_analysis = msg_agent.analyze(second, state_summary=second_state_summary)
            result = order_agent.process_message(phone, second, structured_analysis=second_analysis.structured)
            sf = self._get_state(phone)

            status = "OK" if self._validate(label, sf, result.get("response", "")) else "ERRO"
            final_state = (
                f"status={sf.status_atendimento}, produto={sf.produto}, quantidade={sf.quantidade}, "
                f"tipo_entrega={sf.tipo_entrega}, endereco={sf.endereco}"
            )
            response = (result.get("response", "") or "").replace("\n", " ").strip()
            self.stdout.write(f"{label} | {first} | {second} | {final_state} | {response} | {status}")

    def _mount_fake_state_store(self, fake_store: dict[str, _FakeState]) -> None:
        def _get_or_create_state(phone: str):
            if phone not in fake_store:
                fake_store[phone] = self._FakeState(telefone=phone)
            return fake_store[phone]

        def _update_state(phone: str, **fields):
            state = _get_or_create_state(phone)
            for key, value in fields.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            return state

        def _reset_state(phone: str):
            fake_store[phone] = self._FakeState(telefone=phone)
            return fake_store[phone]

        order_module.get_or_create_state = _get_or_create_state
        order_module.update_state = _update_state
        order_module.reset_state = _reset_state
        fake_catalog = {
            "marmitex_individual": {"nome": "Marmitex Individual", "preco": 21.0},
            "marmita_2_pessoas": {"nome": "Marmita para 2 pessoas", "preco": 44.0},
            "marmita_3_pessoas": {"nome": "Marmita para 3 pessoas", "preco": 60.0},
            "marmita_4_pessoas": {"nome": "Marmita para 4 pessoas", "preco": 76.0},
            "marmita_5_pessoas": {"nome": "Marmita para 5 pessoas", "preco": 92.0},
        }
        order_module.get_order_product = lambda key, only_available=True: fake_catalog.get(key)
        order_module.get_order_product_by_people = lambda people, only_available=True: fake_catalog.get(f"marmita_{people}_pessoas")
        order_module.list_order_products = lambda only_available=True: list(fake_catalog.values())
        order_module.get_order_product_choices = lambda: []

    def _get_state(self, phone: str):
        if phone not in self._fake_store:
            self._fake_store[phone] = self._FakeState(telefone=phone)
        return self._fake_store[phone]

    def _validate(self, label: str, state, response: str) -> bool:
        resp = (response or "").lower()
        if label == "A":
            return (
                state.produto == "marmitex_individual"
                and state.quantidade == 2
                and state.tipo_entrega == "entrega"
                and state.status_atendimento == AtendimentoStatus.AGUARDANDO_ENDERECO
                and "endereco" in resp
            )
        if label == "B":
            return (
                state.produto == "marmita_3_pessoas"
                and state.quantidade == 2
                and state.status_atendimento == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA
                and "entrega" in resp
                and "retirada" in resp
            )
        if label == "C":
            return (
                state.produto == "marmita_4_pessoas"
                and state.quantidade == 1
                and state.status_atendimento == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA
            )
        if label == "D":
            return (
                state.produto == "marmita_5_pessoas"
                and state.quantidade == 1
                and state.tipo_entrega == "retirada"
                and state.status_atendimento == AtendimentoStatus.AGUARDANDO_PAGAMENTO
                and "forma de pagamento" in resp
            )
        if label == "E":
            return (
                state.produto == "marmita"
                and state.quantidade == 2
                and state.status_atendimento == AtendimentoStatus.AGUARDANDO_PRODUTO
                and "nao consegui identificar o tipo" in resp
            )
        return False

from django.core.management.base import BaseCommand

from dataclasses import dataclass, field

from app.agents.conversation_state import AtendimentoStatus
from app.agents.message_agent import MessageAgent
from app.agents.order_agent import OrderAgent
import app.agents.order_agent as order_module


class Command(BaseCommand):
    help = "Simula o OrderAgent consumindo dados estruturados sem quebrar o fluxo legado."

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
        message_agent = MessageAgent()
        order_agent = OrderAgent()
        fake_store: dict[str, Command._FakeState] = {}
        self._mount_fake_state_store(fake_store)
        scenarios = [
            {"message": "quero 3 marmitex", "setup": self._setup_empty},
            {"message": "quero 2 marmitas", "setup": self._setup_empty},
            {"message": "quero 2 marmitas para entregar", "setup": self._setup_empty},
            {"message": "manda uma marmita", "setup": self._setup_empty},
            {"message": "quero marmita para 3 pessoas", "setup": self._setup_empty},
            {"message": "manda uma para 4 pessoas", "setup": self._setup_empty},
        ]

        self.stdout.write(
            "mensagem | extraido | estado_antes | estado_depois | resposta | status"
        )
        self.stdout.write("-" * 220)

        for idx, scenario in enumerate(scenarios, start=1):
            phone = f"SIM_ORDER_STRUCTURED_{idx}"
            fake_store.pop(phone, None)
            scenario["setup"](phone, fake_store)
            state_before = self._get_state(fake_store, phone)
            before_text = (
                f"status={state_before.status_atendimento}, produto={state_before.produto}, quantidade={state_before.quantidade}, "
                f"tipo_entrega={state_before.tipo_entrega}, endereco={state_before.endereco}"
            )

            state_summary = None
            if state_before.ultima_intencao == "fazer_pedido" or state_before.status_atendimento != AtendimentoStatus.INICIO:
                state_summary = {
                    "status_atendimento": state_before.status_atendimento,
                    "ultima_intencao": state_before.ultima_intencao,
                    "aguardando_resposta": state_before.aguardando_resposta,
                    "pedido_atual": {
                        "produto": state_before.produto,
                        "quantidade": state_before.quantidade,
                        "tipo_entrega": state_before.tipo_entrega,
                        "endereco": state_before.endereco,
                        "forma_pagamento": state_before.forma_pagamento,
                    },
                }
            analysis = message_agent.analyze(scenario["message"], state_summary=state_summary)

            result = order_agent.process_message(
                phone,
                scenario["message"],
                structured_analysis=analysis.structured,
            )
            state_after = self._get_state(fake_store, phone)
            ok = self._validate_case(scenario["message"], state_after)
            status = "OK" if ok else "ERRO"

            extracted = (
                f"intencao={analysis.intencao}, produto={analysis.produto}, quantidade={analysis.quantidade}, "
                f"tipo_marmita={analysis.tipo_marmita}, tipo_entrega={analysis.tipo_entrega}, endereco={analysis.endereco}, "
                f"confianca={analysis.confianca:.2f}, precisa_confirmacao={analysis.precisa_confirmacao}"
            )
            after_text = (
                f"status={state_after.status_atendimento}, produto={state_after.produto}, quantidade={state_after.quantidade}, "
                f"tipo_entrega={state_after.tipo_entrega}, endereco={state_after.endereco}"
            )
            response = (result.get("response", "") or "").replace("\n", " ").strip()
            self.stdout.write(f"{scenario['message']} | {extracted} | {before_text} | {after_text} | {response} | {status}")
            fake_store.pop(phone, None)

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
        # Catalogo fake para rodar simulacao sem banco.
        fake_catalog = {
            "marmitex_individual": {"nome": "Marmitex Individual", "preco": 21.0},
            "marmita_2_pessoas": {"nome": "Marmita para 2 pessoas", "preco": 44.0},
            "marmita_3_pessoas": {"nome": "Marmita para 3 pessoas", "preco": 60.0},
            "marmita_4_pessoas": {"nome": "Marmita para 4 pessoas", "preco": 76.0},
            "marmita_5_pessoas": {"nome": "Marmita para 5 pessoas", "preco": 92.0},
        }

        order_module.get_order_product = lambda key, only_available=True: fake_catalog.get(key)
        order_module.get_order_product_by_people = (
            lambda people, only_available=True: fake_catalog.get(f"marmita_{people}_pessoas")
        )
        order_module.list_order_products = lambda only_available=True: list(fake_catalog.values())
        order_module.get_order_product_choices = lambda: [
            {"choice": "1", "key": "marmitex_individual", "nome": "Marmitex Individual", "preco": 21.0, "people_count": None},
            {"choice": "2", "key": "marmita_2_pessoas", "nome": "Marmita para 2 pessoas", "preco": 44.0, "people_count": 2},
            {"choice": "3", "key": "marmita_3_pessoas", "nome": "Marmita para 3 pessoas", "preco": 60.0, "people_count": 3},
            {"choice": "4", "key": "marmita_4_pessoas", "nome": "Marmita para 4 pessoas", "preco": 76.0, "people_count": 4},
            {"choice": "5", "key": "marmita_5_pessoas", "nome": "Marmita para 5 pessoas", "preco": 92.0, "people_count": 5},
        ]
        order_module.format_brl = lambda value: f"R$ {float(value):.2f}".replace(".", ",")

    def _get_state(self, fake_store: dict[str, _FakeState], phone: str):
        if phone not in fake_store:
            fake_store[phone] = self._FakeState(telefone=phone)
        return fake_store[phone]

    def _setup_empty(self, phone: str, fake_store: dict[str, _FakeState]) -> None:
        state = self._get_state(fake_store, phone)
        state.status_atendimento = AtendimentoStatus.INICIO
        state.ultima_intencao = ""

    def _setup_order_in_progress(self, phone: str, fake_store: dict[str, _FakeState]) -> None:
        state = self._get_state(fake_store, phone)
        state.status_atendimento = AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA
        state.ultima_intencao = "fazer_pedido"
        state.produto = "marmitex_individual"
        state.quantidade = 1
        state.valor_unitario = 21.0
        state.valor_total = 21.0
        state.itens_pedido = [
            {
                "produto": "marmitex individual",
                "produto_key": "marmitex_individual",
                "quantidade": 1,
                "valor_unitario": 21.0,
                "subtotal": 21.0,
            }
        ]
        state.aguardando_resposta = "tipo_entrega"

    def _validate_case(self, message: str, state_after) -> bool:
        text = message.lower()
        if text == "quero 3 marmitex":
            return state_after.produto == "marmitex_individual" and state_after.quantidade == 3
        if text == "quero 2 marmitas":
            return (
                state_after.status_atendimento == AtendimentoStatus.AGUARDANDO_PRODUTO
                and state_after.produto == "marmita"
                and state_after.quantidade == 2
                and not state_after.itens_pedido
            )
        if text == "quero 2 marmitas para entregar":
            return (
                state_after.status_atendimento == AtendimentoStatus.AGUARDANDO_PRODUTO
                and state_after.produto == "marmita"
                and state_after.quantidade == 2
                and state_after.tipo_entrega == "entrega"
                and not state_after.itens_pedido
            )
        if text == "manda uma marmita":
            return (
                state_after.status_atendimento == AtendimentoStatus.AGUARDANDO_PRODUTO
                and state_after.produto == "marmita"
                and state_after.quantidade == 1
                and not state_after.itens_pedido
            )
        if text == "quero marmita para 3 pessoas":
            return state_after.produto == "marmita_3_pessoas" and state_after.quantidade == 1
        if text == "manda uma para 4 pessoas":
            return state_after.produto == "marmita_4_pessoas" and state_after.quantidade == 1
        return False

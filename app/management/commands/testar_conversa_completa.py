from dataclasses import dataclass, field, asdict

from django.core.management.base import BaseCommand

from app.agents.orchestrator_agent import OrchestratorAgent
from app.agents.conversation_state import AtendimentoStatus
import app.agents.orchestrator_agent as orchestrator_module
import app.agents.order_agent as order_module


class Command(BaseCommand):
    help = "Teste de regressao ponta a ponta (simulacao em memoria) para conversas sequenciais no OrchestratorAgent."

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
        self._store: dict[str, Command._FakeState] = {}
        self._mount_fake_runtime(self._store)
        orchestrator = OrchestratorAgent()
        self._mount_orchestrator_stubs(orchestrator)

        scenarios = [
            {
                "name": "Cenario 1 - Marmita ambigua + entrega + individual",
                "phone": "5599999990001",
                "messages": ["oi", "quero 2 marmitas para entregar", "individual", "Rua Bahia 1000", "pix"],
                "validator": self._validate_scenario_1,
            },
            {
                "name": "Cenario 2 - Marmitex direto + retirada",
                "phone": "5599999990002",
                "messages": ["oi", "quero 3 marmitex", "vou buscar aí", "dinheiro"],
                "validator": self._validate_scenario_2,
            },
            {
                "name": "Cenario 3 - Marmita 4 pessoas + entrega",
                "phone": "5599999990003",
                "messages": ["manda uma para 4 pessoas", "entrega", "Rua Ceará 500", "cartao"],
                "validator": self._validate_scenario_3,
            },
            {
                "name": "Cenario 4 - Correcao de quantidade",
                "phone": "5599999990004",
                "messages": ["quero 3 marmitex", "na verdade quero 2", "retirada"],
                "validator": self._validate_scenario_4,
            },
            {
                "name": "Cenario 5 - Cliente nao sabe tipo",
                "phone": "5599999990005",
                "messages": ["quero 2 marmitas", "não sei", "para 3 pessoas"],
                "validator": self._validate_scenario_5,
            },
        ]

        passed = 0
        failed = 0
        failures: list[str] = []
        self.stdout.write("tipo_teste=simulacao_em_memoria")
        self.stdout.write("=" * 220)

        for scenario in scenarios:
            phone = scenario["phone"]
            self._store.pop(phone, None)
            transcript = []
            self.stdout.write(f"\n{scenario['name']}")
            self.stdout.write("-" * 220)
            for idx, message in enumerate(scenario["messages"], start=1):
                result = orchestrator.handle_message(message=message, telefone=phone)
                state = self._get_state(phone)
                response = (result.get("final_response") or "").replace("\n", " ").strip()
                state_line = (
                    f"status={state.status_atendimento}, produto={state.produto}, quantidade={state.quantidade}, "
                    f"tipo_entrega={state.tipo_entrega}, endereco={state.endereco}, pagamento={state.forma_pagamento}"
                )
                transcript.append({"message": message, "response": response, "state": asdict(state)})
                self.stdout.write(f"[{idx}] msg={message}")
                self.stdout.write(f"    bot={response}")
                self.stdout.write(f"    estado={state_line}")

            ok, notes = scenario["validator"](transcript)
            status = "OK" if ok else "ERRO"
            self.stdout.write(f"status={status}")
            self.stdout.write(f"observacoes={notes}")
            if ok:
                passed += 1
            else:
                failed += 1
                failures.append(f"{scenario['name']}: {notes}")
            self._store.pop(phone, None)

        self.stdout.write("\n" + "=" * 220)
        self.stdout.write(f"total_cenarios={len(scenarios)}")
        self.stdout.write(f"passaram={passed}")
        self.stdout.write(f"falharam={failed}")
        if failures:
            self.stdout.write("principais_falhas:")
            for item in failures:
                self.stdout.write(f"- {item}")
        else:
            self.stdout.write("principais_falhas=nenhuma")

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
        order_module.get_order_product_choices = lambda: [
            {"choice": "1", "key": "marmitex_individual", "nome": "Marmitex Individual", "preco": 21.0, "people_count": None},
            {"choice": "2", "key": "marmita_2_pessoas", "nome": "Marmita para 2 pessoas", "preco": 44.0, "people_count": 2},
            {"choice": "3", "key": "marmita_3_pessoas", "nome": "Marmita para 3 pessoas", "preco": 60.0, "people_count": 3},
            {"choice": "4", "key": "marmita_4_pessoas", "nome": "Marmita para 4 pessoas", "preco": 76.0, "people_count": 4},
            {"choice": "5", "key": "marmita_5_pessoas", "nome": "Marmita para 5 pessoas", "preco": 92.0, "people_count": 5},
        ]
        order_module.format_brl = lambda value: f"R$ {float(value):.2f}".replace(".", ",")

    def _mount_orchestrator_stubs(self, orchestrator: OrchestratorAgent) -> None:
        orchestrator.database_agent.get_order_status = lambda *_args, **_kwargs: {"implemented": False, "message": "stub", "data": None}
        orchestrator.database_agent.get_payment_status = lambda *_args, **_kwargs: {"implemented": False, "message": "stub", "data": None}
        orchestrator.database_agent.general_lookup = lambda *_args, **_kwargs: {"implemented": False, "message": "stub", "data": None}
        orchestrator.rag_agent.search = lambda *_args, **_kwargs: {"results": []}
        orchestrator.cardapio_agent.get_cardapio = lambda: ""
        # Forca horario de pedidos aberto na simulacao para validar fluxo ponta a ponta.
        orchestrator._is_open_for_orders = lambda: True
        orchestrator._should_block_by_business_hours = lambda *_args, **_kwargs: False

    def _get_state(self, phone: str):
        if phone not in self._store:
            self._store[phone] = self._FakeState(telefone=phone)
        return self._store[phone]

    def _validate_scenario_1(self, transcript: list[dict]) -> tuple[bool, str]:
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        s4 = transcript[3]["state"]
        s5 = transcript[4]["state"]
        checks = [
            s2["produto"] == "marmita" and s2["status_atendimento"] == AtendimentoStatus.AGUARDANDO_PRODUTO,
            s3["produto"] == "marmitex_individual" and s3["quantidade"] == 2 and s3["tipo_entrega"] == "entrega",
            s4["endereco"].lower().find("bahia") >= 0 and s4["status_atendimento"] == AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            s5["forma_pagamento"].lower() == "pix",
        ]
        return (all(checks), "fluxo esperado para ambiguo+entrega+pix" if all(checks) else "estado nao bateu em uma ou mais etapas")

    def _validate_scenario_2(self, transcript: list[dict]) -> tuple[bool, str]:
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        s4 = transcript[3]["state"]
        checks = [
            s2["produto"] == "marmitex_individual" and s2["quantidade"] == 3,
            s3["tipo_entrega"] == "retirada" and s3["status_atendimento"] == AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            s3["endereco"] == "retirada no local",
            s4["forma_pagamento"].lower() == "dinheiro",
        ]
        return (all(checks), "fluxo esperado para retirada" if all(checks) else "falha em produto/quantidade/retirada/pagamento")

    def _validate_scenario_3(self, transcript: list[dict]) -> tuple[bool, str]:
        s1 = transcript[0]["state"]
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        s4 = transcript[3]["state"]
        checks = [
            s1["produto"] == "marmita_4_pessoas" and s1["quantidade"] == 1,
            s3["tipo_entrega"] == "entrega",
            "cear" in s3["endereco"].lower(),
            s4["forma_pagamento"].lower() == "cartao",
        ]
        return (all(checks), "fluxo esperado para marmita 4 pessoas" if all(checks) else "falha em uma etapa do cenario 3")

    def _validate_scenario_4(self, transcript: list[dict]) -> tuple[bool, str]:
        s1 = transcript[0]["state"]
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        checks = [
            s1["quantidade"] == 3,
            s2["quantidade"] == 2,
            s3["tipo_entrega"] == "retirada" and s3["endereco"] == "retirada no local",
        ]
        return (all(checks), "fluxo esperado para alteracao de quantidade" if all(checks) else "quantidade/retirada nao bateu")

    def _validate_scenario_5(self, transcript: list[dict]) -> tuple[bool, str]:
        s1 = transcript[0]["state"]
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        r2 = transcript[1]["response"].lower()
        checks = [
            s1["produto"] == "marmita" and s1["status_atendimento"] == AtendimentoStatus.AGUARDANDO_PRODUTO,
            s2["produto"] == "marmita" and s2["quantidade"] == 2 and ("não consegui identificar o tipo" in r2 or "nao consegui identificar o tipo" in r2),
            s3["produto"] == "marmita_3_pessoas" and s3["quantidade"] == 2 and s3["status_atendimento"] == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
        ]
        return (all(checks), "fluxo esperado para duvida de tipo" if all(checks) else "falha no tratamento de nao sei")

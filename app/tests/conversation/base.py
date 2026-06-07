from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime

from django.test import SimpleTestCase

from app.agents.conversation_state import AtendimentoStatus
from app.agents.orchestrator_agent import OrchestratorAgent
from app.conversation.contracts import AgentResponseContract
from app.conversation.state_machine import ConversationStateMachine
import app.agents.orchestrator_agent as orchestrator_module
import app.agents.order_agent as order_module


class ConversationFlowBaseTestCase(SimpleTestCase):
    @dataclass
    class _ConversationStep:
        user_message: str
        bot_response: str
        raw_result: dict
        before_awaiting_response: str
        status_atendimento: str
        aguardando_resposta: str
        itens_pedido: list[dict]
        valor_total: float
        tipo_entrega: str
        forma_pagamento: str

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
        atualizado_em: datetime = field(default_factory=datetime.utcnow)

    def setUp(self) -> None:
        super().setUp()
        self._store: dict[str, ConversationFlowBaseTestCase._FakeState] = {}
        self._customer_names: dict[str, str] = {}
        self.state_machine = ConversationStateMachine()
        self._original_orch_get = orchestrator_module.get_or_create_state
        self._original_orch_update = orchestrator_module.update_state
        self._original_orch_reset = orchestrator_module.reset_state
        self._original_order_get = order_module.get_or_create_state
        self._original_order_update = order_module.update_state
        self._original_order_reset = order_module.reset_state
        self._original_order_get_customer_name = order_module.OrderAgent._get_customer_name
        self._original_order_set_customer_name = order_module.OrderAgent._set_customer_name
        self._original_localdate = orchestrator_module.timezone.localdate
        self._original_orch_get_order_product = orchestrator_module.get_order_product
        self._original_orch_get_order_product_by_people = orchestrator_module.get_order_product_by_people
        self._original_orch_get_order_product_choices = orchestrator_module.get_order_product_choices
        self._original_orch_list_order_products = orchestrator_module.list_order_products
        self._original_orch_format_brl = orchestrator_module.format_brl
        self._original_order_get_order_product = order_module.get_order_product
        self._original_order_get_order_product_by_people = order_module.get_order_product_by_people
        self._original_order_get_order_product_choices = order_module.get_order_product_choices
        self._original_order_list_order_products = order_module.list_order_products
        self._original_order_format_brl = order_module.format_brl
        self._original_list_available_complements = order_module.OrderAgent._list_available_complements
        self._mount_fake_runtime()

        self.orchestrator = OrchestratorAgent()
        self.orchestrator.instructions_agent.get_instructions = lambda: ""
        self.orchestrator.rag_agent.search = lambda *_args, **_kwargs: {"results": []}
        self.orchestrator.cardapio_agent.get_cardapio = lambda: (
            "## segunda-feira\n"
            "- Feijoada\n- Arroz\n- Farofa\n"
            "## terca-feira\n"
            "- Frango grelhado\n- Arroz\n- Feijão\n"
            "## quarta-feira\n"
            "- Bife acebolado\n- Arroz\n- Feijão tropeiro\n"
            "## quinta-feira\n"
            "- Strogonoff\n- Arroz\n- Batata palha\n"
            "## sexta-feira\n"
            "- Peixe frito\n- Arroz\n- Purê de batata\n"
            "## sabado\n"
            "- Costela assada\n- Arroz\n- Mandioca\n"
        )
        self.orchestrator._is_open_for_orders = lambda: True
        self.orchestrator._should_block_by_business_hours = lambda *_args, **_kwargs: False
        orchestrator_module.timezone.localdate = lambda: date(2026, 5, 31)

    def tearDown(self) -> None:
        orchestrator_module.get_or_create_state = self._original_orch_get
        orchestrator_module.update_state = self._original_orch_update
        orchestrator_module.reset_state = self._original_orch_reset
        order_module.get_or_create_state = self._original_order_get
        order_module.update_state = self._original_order_update
        order_module.reset_state = self._original_order_reset
        orchestrator_module.timezone.localdate = self._original_localdate
        orchestrator_module.get_order_product = self._original_orch_get_order_product
        orchestrator_module.get_order_product_by_people = self._original_orch_get_order_product_by_people
        orchestrator_module.get_order_product_choices = self._original_orch_get_order_product_choices
        orchestrator_module.list_order_products = self._original_orch_list_order_products
        orchestrator_module.format_brl = self._original_orch_format_brl
        order_module.get_order_product = self._original_order_get_order_product
        order_module.get_order_product_by_people = self._original_order_get_order_product_by_people
        order_module.get_order_product_choices = self._original_order_get_order_product_choices
        order_module.list_order_products = self._original_order_list_order_products
        order_module.format_brl = self._original_order_format_brl
        order_module.OrderAgent._list_available_complements = self._original_list_available_complements
        order_module.OrderAgent._get_customer_name = self._original_order_get_customer_name
        order_module.OrderAgent._set_customer_name = self._original_order_set_customer_name
        super().tearDown()

    def _mount_fake_runtime(self) -> None:
        def _get_or_create_state(phone: str):
            if phone not in self._store:
                self._store[phone] = self._FakeState(telefone=phone)
            return self._store[phone]

        def _update_state(phone: str, **fields):
            state = _get_or_create_state(phone)
            for key, value in fields.items():
                if hasattr(state, key):
                    setattr(state, key, value)
            state.atualizado_em = datetime.utcnow()
            return state

        def _reset_state(phone: str):
            self._store[phone] = self._FakeState(telefone=phone)
            return self._store[phone]

        orchestrator_module.get_or_create_state = _get_or_create_state
        orchestrator_module.update_state = _update_state
        orchestrator_module.reset_state = _reset_state
        order_module.get_or_create_state = _get_or_create_state
        order_module.update_state = _update_state
        order_module.reset_state = _reset_state

        fake_catalog = {
            "marmitex_individual": {"nome": "Marmitex Individual", "preco": 21.0},
            "marmita_2_pessoas": {"nome": "Marmita para 2 pessoas", "preco": 65.0},
            "marmita_3_pessoas": {"nome": "Marmita para 3 pessoas", "preco": 85.0},
            "marmita_4_pessoas": {"nome": "Marmita para 4 pessoas", "preco": 105.0},
            "marmita_5_pessoas": {"nome": "Marmita para 5 pessoas", "preco": 125.0},
        }

        orchestrator_module.get_order_product = lambda key, only_available=True: fake_catalog.get(key)
        orchestrator_module.get_order_product_by_people = (
            lambda people, only_available=True: fake_catalog.get(f"marmita_{people}_pessoas")
        )
        orchestrator_module.list_order_products = lambda only_available=True: list(fake_catalog.values())
        orchestrator_module.get_order_product_choices = lambda: [
            {"choice": "1", "key": "marmitex_individual", "nome": "Marmitex Individual", "preco": 21.0, "people_count": None},
            {"choice": "2", "key": "marmita_2_pessoas", "nome": "Marmita para 2 pessoas", "preco": 65.0, "people_count": 2},
            {"choice": "3", "key": "marmita_3_pessoas", "nome": "Marmita para 3 pessoas", "preco": 85.0, "people_count": 3},
            {"choice": "4", "key": "marmita_4_pessoas", "nome": "Marmita para 4 pessoas", "preco": 105.0, "people_count": 4},
            {"choice": "5", "key": "marmita_5_pessoas", "nome": "Marmita para 5 pessoas", "preco": 125.0, "people_count": 5},
        ]
        orchestrator_module.format_brl = lambda value: f"R$ {float(value):.2f}".replace(".", ",")

        order_module.get_order_product = orchestrator_module.get_order_product
        order_module.get_order_product_by_people = orchestrator_module.get_order_product_by_people
        order_module.list_order_products = orchestrator_module.list_order_products
        order_module.get_order_product_choices = orchestrator_module.get_order_product_choices
        order_module.format_brl = orchestrator_module.format_brl

        def _get_customer_name(_self, phone: str) -> str:
            return self._customer_names.get(phone, "")

        def _set_customer_name(_self, phone: str, name: str) -> str:
            cleaned = " ".join(part.capitalize() for part in name.strip().split())
            if not cleaned:
                return ""
            self._customer_names[phone] = cleaned
            return cleaned

        order_module.OrderAgent._get_customer_name = _get_customer_name
        order_module.OrderAgent._set_customer_name = _set_customer_name

    def _enable_fake_complements(self) -> None:
        fake_complements = [
            {"choice": "1", "produto": "água mineral", "produto_key": "complemento_101", "produto_id": 101, "valor_unitario": 4.0, "categoria": "bebida"},
            {"choice": "2", "produto": "refrigerante lata", "produto_key": "complemento_102", "produto_id": 102, "valor_unitario": 6.0, "categoria": "bebida"},
            {"choice": "3", "produto": "ovo adicional", "produto_key": "complemento_103", "produto_id": 103, "valor_unitario": 2.5, "categoria": "adicional"},
            {"choice": "4", "produto": "sobremesa do dia", "produto_key": "complemento_104", "produto_id": 104, "valor_unitario": 7.0, "categoria": "sobremesa"},
        ]
        order_module.OrderAgent._list_available_complements = lambda _self: list(fake_complements)

    def _build_main_item(self, produto: str = "marmitex_individual", quantidade: int = 2, valor_unitario: float = 21.0) -> list[dict]:
        produto_nome = "marmitex individual" if produto == "marmitex_individual" else produto.replace("_", " ")
        if produto == "marmita_3_pessoas":
            produto_nome = "marmita para 3 pessoas"
        return [
            {
                "produto": produto_nome,
                "produto_key": produto,
                "produto_id": 1,
                "quantidade": quantidade,
                "valor_unitario": valor_unitario,
                "subtotal": round(quantidade * valor_unitario, 2),
            }
        ]

    def _set_state(self, telefone: str, **fields):
        state = self._store.get(telefone)
        if state is None:
            state = self._FakeState(telefone=telefone)
            self._store[telefone] = state
        for key, value in fields.items():
            setattr(state, key, value)
        state.atualizado_em = datetime.utcnow()
        return state

    def _assert_delivery_prompt(self, response: str) -> None:
        self.assertIn("Você prefere:", response)
        self.assertIn("1 - Entrega", response)
        self.assertIn("2 - Retirada no local", response)

    def _run_conversation(self, telefone: str, messages: list[str]) -> list[_ConversationStep]:
        history: list[ConversationFlowBaseTestCase._ConversationStep] = []
        for message in messages:
            current_state = self._store.get(telefone)
            before_awaiting_response = current_state.aguardando_resposta if current_state else ""
            result = self.orchestrator.handle_message(message, telefone=telefone)
            state = self._store[telefone]
            history.append(
                self._ConversationStep(
                    user_message=message,
                    bot_response=result["final_response"],
                    raw_result=deepcopy(result),
                    before_awaiting_response=before_awaiting_response,
                    status_atendimento=state.status_atendimento,
                    aguardando_resposta=state.aguardando_resposta,
                    itens_pedido=deepcopy(state.itens_pedido),
                    valor_total=float(state.valor_total or 0.0),
                    tipo_entrega=state.tipo_entrega,
                    forma_pagamento=state.forma_pagamento,
                )
            )
        return history

    def _assert_contract_matches_step(
        self,
        step: _ConversationStep,
        *,
        expected_intent: str | None = None,
        expected_next_state: str | None = None,
        expected_awaiting_response: str | None = None,
        expected_payment_updated: bool | None = None,
    ) -> AgentResponseContract:
        contract = AgentResponseContract.from_orchestrator_response(step.raw_result)
        self.assertTrue(contract.success)
        self.assertEqual(contract.message, step.bot_response)
        self.assertEqual(contract.raw_response, step.raw_result)
        self.assertFalse(contract.requires_human)
        self.assertEqual(contract.errors, [])
        if expected_intent is not None:
            self.assertEqual(contract.intent, expected_intent)
        if expected_next_state is not None:
            self.assertEqual(contract.next_state, expected_next_state)
        if expected_awaiting_response is not None:
            self.assertEqual(contract.awaiting_response, expected_awaiting_response)
        if expected_payment_updated is not None:
            self.assertEqual(contract.payment_updated, expected_payment_updated)
        return contract

    def _assert_state_machine_transition(
        self,
        step: _ConversationStep,
        *,
        allow_not_mapped: bool = False,
    ) -> None:
        expected_next = self.state_machine.get_expected_next_awaiting_response(
            step.before_awaiting_response,
            step.user_message,
        )
        actual_next = step.aguardando_resposta
        if expected_next == self.state_machine.NOT_MAPPED:
            if allow_not_mapped:
                return
            self.fail(
                "StateMachine retornou not_mapped para transição estável: "
                f"before={step.before_awaiting_response!r}, "
                f"message={step.user_message!r}, after={actual_next!r}"
            )
        if not self.state_machine.is_transition_allowed(
            step.before_awaiting_response,
            step.user_message,
            actual_next,
        ):
            explanation = self.state_machine.explain_transition(
                step.before_awaiting_response,
                step.user_message,
            )
            self.fail(
                "Transição divergente da StateMachine: "
                f"before={step.before_awaiting_response!r}, "
                f"message={step.user_message!r}, "
                f"expected={explanation.expected_next_awaiting_response!r}, "
                f"actual={actual_next!r}. "
                f"Info: {explanation.description}"
            )

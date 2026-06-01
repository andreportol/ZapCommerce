from dataclasses import dataclass, field
from datetime import date

from django.test import SimpleTestCase

from app.agents.conversation_state import AtendimentoStatus
from app.agents.orchestrator_agent import OrchestratorAgent
import app.agents.orchestrator_agent as orchestrator_module
import app.agents.order_agent as order_module


class CardapioDayContextTests(SimpleTestCase):
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

    def setUp(self) -> None:
        super().setUp()
        self._store: dict[str, CardapioDayContextTests._FakeState] = {}
        self._original_orch_get = orchestrator_module.get_or_create_state
        self._original_orch_update = orchestrator_module.update_state
        self._original_orch_reset = orchestrator_module.reset_state
        self._original_order_get = order_module.get_or_create_state
        self._original_order_update = order_module.update_state
        self._original_order_reset = order_module.reset_state
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
        self._mount_fake_runtime()

        self.orchestrator = OrchestratorAgent()
        self.orchestrator.instructions_agent.get_instructions = lambda: ""
        self.orchestrator.rag_agent.search = lambda *_args, **_kwargs: {"results": []}
        self.orchestrator.cardapio_agent.get_cardapio = lambda: (
            "## segunda-feira\n"
            "- Feijoada\n- Arroz\n- Farofa\n"
            "## terca-feira\n"
            "- Frango grelhado\n- Arroz\n- Feijao\n"
            "## quarta-feira\n"
            "- Bife acebolado\n- Arroz\n- Feijao tropeiro\n"
            "## quinta-feira\n"
            "- Strogonoff\n- Arroz\n- Batata palha\n"
            "## sexta-feira\n"
            "- Peixe frito\n- Arroz\n- Pure\n"
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
        super().tearDown()

    def test_menu_option_two_lists_days_and_saves_day_context(self) -> None:
        result = self.orchestrator.handle_message("2", telefone="5511999990001")
        state = self._store["5511999990001"]

        self.assertIn("Cardápios disponíveis:", result["final_response"])
        self.assertIn("Digite o número ou o nome do dia que deseja consultar.", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "dia_cardapio")
        self.assertEqual(state.ultima_intencao, "consultar_cardapio")

    def test_day_context_interprets_number_two_as_tuesday(self) -> None:
        self.orchestrator.handle_message("2", telefone="5511999990002")
        result = self.orchestrator.handle_message("2", telefone="5511999990002")
        state = self._store["5511999990002"]

        self.assertIn("O cardápio de terça-feira é:", result["final_response"])
        self.assertIn("Frango grelhado", result["final_response"])
        self.assertEqual(state.ultima_intencao, "consultar_cardapio:terca-feira")
        self.assertEqual(state.aguardando_resposta, "")

    def test_day_context_interprets_number_one_as_monday(self) -> None:
        self.orchestrator.handle_message("2", telefone="5511999990003")
        result = self.orchestrator.handle_message("1", telefone="5511999990003")

        self.assertIn("O cardápio de segunda-feira é:", result["final_response"])
        self.assertIn("Feijoada", result["final_response"])

    def test_day_context_accepts_tuesday_name(self) -> None:
        self.orchestrator.handle_message("2", telefone="5511999990004")
        result = self.orchestrator.handle_message("terça", telefone="5511999990004")

        self.assertIn("O cardápio de terça-feira é:", result["final_response"])
        self.assertIn("Frango grelhado", result["final_response"])

    def test_day_context_accepts_natural_language_for_wednesday(self) -> None:
        self.orchestrator.handle_message("2", telefone="5511999990005")
        result = self.orchestrator.handle_message("quero o de quarta", telefone="5511999990005")

        self.assertIn("O cardápio de quarta-feira é:", result["final_response"])
        self.assertIn("Bife acebolado", result["final_response"])

    def test_number_two_outside_day_context_keeps_main_menu_behavior(self) -> None:
        result = self.orchestrator.handle_message("2", telefone="5511999990006")
        state = self._store["5511999990006"]

        self.assertIn("Cardápios disponíveis:", result["final_response"])
        self.assertNotIn("O cardápio de terça-feira é:", result["final_response"])
        self.assertEqual(state.ultima_intencao, "consultar_cardapio")
        self.assertEqual(state.aguardando_resposta, "dia_cardapio")

    def test_delivery_bairro_followup_gets_useful_response(self) -> None:
        first = self.orchestrator.handle_message("vcs entregam?", telefone="5511999990007")
        state_after_first = self._store["5511999990007"]

        self.assertIn("me envie o endereço ou o bairro", first["final_response"])
        self.assertEqual(state_after_first.aguardando_resposta, "entrega_bairro_ou_endereco")

        second = self.orchestrator.handle_message("bairro tijuca", telefone="5511999990007")
        state_after_second = self._store["5511999990007"]

        self.assertNotIn("Não encontrei dados suficientes", second["final_response"])
        self.assertIn("Ainda não consigo confirmar automaticamente a entrega por bairro", second["final_response"])
        self.assertIn("bairro Tijuca", second["final_response"])
        self.assertEqual(state_after_second.aguardando_resposta, "")

    def test_future_contact_day_does_not_turn_into_reservation_for_first_day(self) -> None:
        result = self.orchestrator.handle_message(
            "segunda-feira eu te envio uma mensagem para reservar a marmitex de terça-feira",
            telefone="5511999990008",
        )

        self.assertIn("Na segunda-feira, entre 9h e 12h30", result["final_response"])
        self.assertIn("reservar a marmitex de terça-feira", result["final_response"])
        self.assertNotIn("reservar para segunda-feira", result["final_response"])

    def test_acknowledgement_ok_returns_short_closing_response(self) -> None:
        result = self.orchestrator.handle_message("ok", telefone="5511999990009")
        self.assertIn("Combinado 😊", result["final_response"])
        self.assertIn("Quando quiser, é só me chamar.", result["final_response"])

    def test_acknowledgement_obrigado_returns_polite_response(self) -> None:
        result = self.orchestrator.handle_message("obrigado", telefone="5511999990010")
        self.assertIn("Combinado 😊", result["final_response"])
        self.assertIn("Quando quiser, é só me chamar.", result["final_response"])

    def test_acknowledgement_beleza_returns_short_response(self) -> None:
        result = self.orchestrator.handle_message("beleza", telefone="5511999990011")
        self.assertIn("Combinado 😊", result["final_response"])
        self.assertIn("Quando quiser, é só me chamar.", result["final_response"])

    def test_outside_hours_greeting_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("oi", telefone="5511999990012")
        self._assert_full_outside_hours_message(result["final_response"])

    def test_outside_hours_second_message_returns_short_message(self) -> None:
        self._configure_outside_hours()
        self.orchestrator.handle_message("oi", telefone="5511999990013")
        result = self.orchestrator.handle_message("quero ver o cardápio", telefone="5511999990013")
        self._assert_short_outside_hours_message(result["final_response"])

    def test_outside_hours_third_message_returns_short_message(self) -> None:
        self._configure_outside_hours()
        self.orchestrator.handle_message("oi", telefone="5511999990014")
        self.orchestrator.handle_message("quero ver o cardápio", telefone="5511999990014")
        result = self.orchestrator.handle_message("saber sobre valores", telefone="5511999990014")
        self._assert_short_outside_hours_message(result["final_response"])

    def test_outside_hours_human_request_returns_specific_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("falar com atendente", telefone="5511999990015")
        self.assertIn("No momento estamos fora do horário de atendimento.", result["final_response"])
        self.assertIn("Deixe sua mensagem que a atendente responderá assim que possível.", result["final_response"])

    def test_outside_hours_acknowledgement_returns_short_closing(self) -> None:
        self._configure_outside_hours()
        self.orchestrator.handle_message("oi", telefone="5511999990016")
        result = self.orchestrator.handle_message("ok", telefone="5511999990016")
        self.assertIn("Combinado 😊", result["final_response"])
        self.assertIn("Quando estiver dentro do horário, é só me chamar.", result["final_response"])

    def test_outside_hours_menu_option_two_does_not_list_cardapio(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("2", telefone="5511999990017")
        self._assert_full_outside_hours_message(result["final_response"])
        self.assertNotIn("Cardápios disponíveis:", result["final_response"])

    def test_outside_hours_cardapio_question_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("qual o cardápio de segunda?", telefone="5511999990018")
        self._assert_full_outside_hours_message(result["final_response"])

    def test_outside_hours_delivery_price_question_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("qual valor da entrega?", telefone="5511999990023")
        self._assert_full_outside_hours_message(result["final_response"])

    def test_outside_hours_bairro_message_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("bairro tijuca", telefone="5511999990024")
        self._assert_full_outside_hours_message(result["final_response"])

    def test_outside_hours_reservation_message_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("quero reservar", telefone="5511999990025")
        self._assert_full_outside_hours_message(result["final_response"])

    def test_outside_hours_order_message_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("quero 2 marmitex", telefone="5511999990026")
        self._assert_full_outside_hours_message(result["final_response"])

    def test_inside_hours_menu_option_two_still_opens_cardapio(self) -> None:
        result = self.orchestrator.handle_message("2", telefone="5511999990019")
        self.assertIn("Cardápios disponíveis:", result["final_response"])

    def test_inside_hours_order_message_still_starts_order(self) -> None:
        result = self.orchestrator.handle_message("quero 2 marmitex", telefone="5511999990020")
        self.assertIn("Seu pedido ficou assim", result["final_response"])

    def test_inside_hours_delivery_question_still_gets_delivery_response(self) -> None:
        result = self.orchestrator.handle_message("vcs entregam?", telefone="5511999990021")
        self.assertIn("Fazemos entrega, sim", result["final_response"])

    def test_inside_hours_price_question_still_gets_price_response(self) -> None:
        result = self.orchestrator.handle_message("qual o valor da marmitex?", telefone="5511999990022")
        self.assertIn("A marmitex individual custa", result["final_response"])

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
            "marmita_2_pessoas": {"nome": "Marmita para 2 pessoas", "preco": 44.0},
            "marmita_3_pessoas": {"nome": "Marmita para 3 pessoas", "preco": 60.0},
            "marmita_4_pessoas": {"nome": "Marmita para 4 pessoas", "preco": 76.0},
            "marmita_5_pessoas": {"nome": "Marmita para 5 pessoas", "preco": 92.0},
        }

        orchestrator_module.get_order_product = lambda key, only_available=True: fake_catalog.get(key)
        orchestrator_module.get_order_product_by_people = (
            lambda people, only_available=True: fake_catalog.get(f"marmita_{people}_pessoas")
        )
        orchestrator_module.list_order_products = lambda only_available=True: list(fake_catalog.values())
        orchestrator_module.get_order_product_choices = lambda: [
            {"choice": "1", "key": "marmitex_individual", "nome": "Marmitex Individual", "preco": 21.0, "people_count": None},
            {"choice": "2", "key": "marmita_2_pessoas", "nome": "Marmita para 2 pessoas", "preco": 44.0, "people_count": 2},
            {"choice": "3", "key": "marmita_3_pessoas", "nome": "Marmita para 3 pessoas", "preco": 60.0, "people_count": 3},
            {"choice": "4", "key": "marmita_4_pessoas", "nome": "Marmita para 4 pessoas", "preco": 76.0, "people_count": 4},
            {"choice": "5", "key": "marmita_5_pessoas", "nome": "Marmita para 5 pessoas", "preco": 92.0, "people_count": 5},
        ]
        orchestrator_module.format_brl = lambda value: f"R$ {float(value):.2f}".replace(".", ",")

        order_module.get_order_product = orchestrator_module.get_order_product
        order_module.get_order_product_by_people = orchestrator_module.get_order_product_by_people
        order_module.list_order_products = orchestrator_module.list_order_products
        order_module.get_order_product_choices = orchestrator_module.get_order_product_choices
        order_module.format_brl = orchestrator_module.format_brl

    def _configure_outside_hours(self) -> None:
        self.orchestrator._is_open_for_orders = lambda: False
        self.orchestrator._should_block_by_business_hours = (
            OrchestratorAgent._should_block_by_business_hours.__get__(self.orchestrator, OrchestratorAgent)
        )

    def _assert_full_outside_hours_message(self, response: str) -> None:
        self.assertIn("No momento estamos fora do horário de atendimento.", response)
        self.assertIn("Pedidos/encomendas:", response)
        self.assertIn("segunda a sábado, das 9h às 12h30.", response)
        self.assertIn("Entregas e retiradas:", response)
        self.assertIn("das 11h às 13h.", response)
        self.assertIn(
            "Por favor, chame dentro do horário para fazer pedidos, consultar cardápios, valores ou informações sobre entrega.",
            response,
        )
        self.assertIn("Se quiser, deixe sua mensagem que a atendente responderá assim que possível.", response)

    def _assert_short_outside_hours_message(self, response: str) -> None:
        self.assertIn("Ainda estamos fora do horário de atendimento 😊", response)
        self.assertIn(
            "Por favor, chame de segunda a sábado, das 9h às 12h30, para consultar cardápio, valores, entrega ou fazer pedidos.",
            response,
        )

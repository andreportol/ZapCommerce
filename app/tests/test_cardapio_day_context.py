from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from app.agents.conversation_state import AtendimentoStatus
from app.agents.orchestrator_agent import OrchestratorAgent
import app.agents.orchestrator_agent as orchestrator_module
import app.agents.order_agent as order_module
import app.services as services_module


class CardapioDayContextTests(SimpleTestCase):
    class _FakeQueryset(list):
        def order_by(self, *_args, **_kwargs):
            return self

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
        self._store: dict[str, CardapioDayContextTests._FakeState] = {}
        self._customer_names: dict[str, str] = {}
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
        self._original_service_handle_message = services_module.orchestrator_agent.handle_message
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
        services_module.orchestrator_agent.handle_message = self._original_service_handle_message
        order_module.OrderAgent._get_customer_name = self._original_order_get_customer_name
        order_module.OrderAgent._set_customer_name = self._original_order_set_customer_name
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

    def test_greeting_followed_by_option_two_opens_cardapio_flow(self) -> None:
        telefone = "5511999990030"

        self.orchestrator.handle_message("Oi", telefone=telefone)
        result = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Cardápios disponíveis:", result["final_response"])
        self.assertNotIn("Como posso ajudar?", result["final_response"])
        self.assertEqual(state.ultima_intencao, "consultar_cardapio")
        self.assertEqual(state.aguardando_resposta, "dia_cardapio")

    def test_greeting_followed_by_option_one_starts_order_flow(self) -> None:
        telefone = "5511999990032"

        first = self.orchestrator.handle_message("Oi", telefone=telefone)
        result = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("1 - Fazer pedido", first["final_response"])
        self.assertIn("Perfeito", result["final_response"])
        self.assertIn("Você deseja:", result["final_response"])
        self.assertIn("Marmitex Individual", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_PRODUTO)
        self.assertEqual(state.ultima_intencao, "fazer_pedido")

    def test_greeting_followed_by_option_two_shows_todays_menu(self) -> None:
        telefone = "5511999990033"
        original_localdate = orchestrator_module.timezone.localdate
        orchestrator_module.timezone.localdate = lambda: date(2026, 6, 1)

        try:
            self.orchestrator.handle_message("Oi", telefone=telefone)
            result = self.orchestrator.handle_message("2", telefone=telefone)
            state = self._store[telefone]
        finally:
            orchestrator_module.timezone.localdate = original_localdate

        self.assertIn("O cardápio de hoje é", result["final_response"])
        self.assertIn("Feijoada", result["final_response"])
        self.assertEqual(state.ultima_intencao, "consultar_cardapio:segunda-feira")
        self.assertEqual(state.aguardando_resposta, "")

    def test_option_two_with_whatsapp_formatting_character_still_opens_cardapio(self) -> None:
        result = self.orchestrator.handle_message("\u200e2.", telefone="5511999990031")
        state = self._store["5511999990031"]

        self.assertIn("Cardápios disponíveis:", result["final_response"])
        self.assertNotIn("Como posso ajudar?", result["final_response"])
        self.assertEqual(state.ultima_intencao, "consultar_cardapio")
        self.assertEqual(state.aguardando_resposta, "dia_cardapio")

    def test_cardapio_then_hours_question_returns_hours_instead_of_menu(self) -> None:
        telefone = "5511999990034"

        self.orchestrator.handle_message("Oi", telefone=telefone)
        second = self.orchestrator.handle_message("2", telefone=telefone)
        result = self.orchestrator.handle_message("Qual o horário de funcionamento?", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Cardápios disponíveis:", second["final_response"])
        self.assertIn("Funcionamos nos seguintes horários:", result["final_response"])
        self.assertIn("Pedidos/encomendas:", result["final_response"])
        self.assertIn("Entregas e retiradas:", result["final_response"])
        self.assertNotIn("Como posso ajudar?", result["final_response"])
        self.assertEqual(state.ultima_intencao, "consultar_horario")

    def test_opening_hours_question_returns_hours(self) -> None:
        result = self.orchestrator.handle_message("Que horas abre?", telefone="5511999990035")
        self.assertIn("Funcionamos nos seguintes horários:", result["final_response"])
        self.assertIn("* Segunda-feira: 9h às 12h30", result["final_response"])

    def test_menu_option_three_returns_numbered_information_list(self) -> None:
        telefone = "5511999990055"

        first = self.orchestrator.handle_message("Oi", telefone=telefone)
        result = self.orchestrator.handle_message("3", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("1 - Fazer pedido", first["final_response"])
        self.assertIn("Trabalhamos com as seguintes opções", result["final_response"])
        self.assertIn("1 - Marmitex Individual", result["final_response"])
        self.assertIn("2 - Marmita para 2 pessoas", result["final_response"])
        self.assertIn("5 - Marmita para 5 pessoas", result["final_response"])
        self.assertIn("proprietária", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.INICIO)
        self.assertEqual(state.ultima_intencao, "menu_principal")

    def test_cardapio_followup_quantity_for_specific_day_starts_order(self) -> None:
        telefone = "5511999990051"

        cardapio = self.orchestrator.handle_message("Eu quero o cardápio de quinta-feira", telefone=telefone)
        result = self.orchestrator.handle_message("Eu quero duas", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("O cardápio de quinta-feira é:", cardapio["final_response"])
        self.assertIn("Seu pedido ficou assim", result["final_response"])
        self.assertIn("* 2 marmitex individuais: R$ 42,00", result["final_response"])
        self.assertIn("Você prefere:", result["final_response"])
        self.assertIn("cardápio de quinta-feira", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
        self.assertEqual(state.ultima_intencao, "fazer_pedido")

    def test_cardapio_followup_quantity_for_today_starts_order(self) -> None:
        telefone = "5511999990052"
        original_localdate = orchestrator_module.timezone.localdate
        orchestrator_module.timezone.localdate = lambda: date(2026, 6, 6)

        try:
            cardapio = self.orchestrator.handle_message("2", telefone=telefone)
            result = self.orchestrator.handle_message("quero duas", telefone=telefone)
            state = self._store[telefone]
        finally:
            orchestrator_module.timezone.localdate = original_localdate

        self.assertIn("O cardápio de hoje é:", cardapio["final_response"])
        self.assertIn("Seu pedido ficou assim", result["final_response"])
        self.assertIn("* 2 marmitex individuais: R$ 42,00", result["final_response"])
        self.assertIn("Você prefere:", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
        self.assertEqual(state.ultima_intencao, "fazer_pedido")

    def test_cardapio_displays_feijao_and_pure_with_accents(self) -> None:
        quarta = self.orchestrator.handle_message("quarta-feira", telefone="5511999990053")
        sexta = self.orchestrator.handle_message("sexta-feira", telefone="5511999990054")

        self.assertIn("Feijão tropeiro", quarta["final_response"])
        self.assertIn("Purê de batata", sexta["final_response"])

    def test_faz_entrega_still_returns_delivery_response(self) -> None:
        result = self.orchestrator.handle_message("Faz entrega?", telefone="5511999990036")
        self.assertIn("Fazemos entrega, sim", result["final_response"])

    def test_location_question_returns_configuration_message(self) -> None:
        result = self.orchestrator.handle_message("Onde fica?", telefone="5511999990037")
        self.assertIn("ainda não foi configurado no sistema", result["final_response"])
        self.assertNotIn("Como posso ajudar?", result["final_response"])

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
        result = self.orchestrator.handle_message("tem promoção?", telefone="5511999990013")
        self._assert_short_outside_hours_message(result["final_response"])

    def test_outside_hours_third_message_returns_short_message(self) -> None:
        self._configure_outside_hours()
        self.orchestrator.handle_message("oi", telefone="5511999990014")
        self.orchestrator.handle_message("tem promoção?", telefone="5511999990014")
        result = self.orchestrator.handle_message("saber sobre valores", telefone="5511999990014")
        self._assert_short_outside_hours_message(result["final_response"])

    def test_outside_hours_human_request_returns_specific_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("Ninguém para tirar dúvidas?", telefone="5511999990015")
        self.assertIn("não há atendente disponível", result["final_response"])
        self.assertIn("Horários:", result["final_response"])
        self.assertIn("* Segunda-feira: 9h às 12h30", result["final_response"])

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

    def test_outside_hours_cardapio_question_returns_cardapio_with_notice(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("qual o cardápio de segunda?", telefone="5511999990018")
        self.assertIn("O cardápio de segunda-feira é:", result["final_response"])
        self.assertIn("Feijoada", result["final_response"])
        self.assertIn("fora do horário de atendimento", result["final_response"])

    def test_outside_hours_delivery_question_returns_contextual_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("Quero saber se fazem entrega", telefone="5511999990023")
        self.assertIn("Fazemos entrega sim", result["final_response"])
        self.assertIn("consultar taxa, região atendida e fazer seu pedido", result["final_response"])
        self.assertIn("Horários de atendimento:", result["final_response"])

    def test_outside_hours_bairro_message_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("bairro tijuca", telefone="5511999990024")
        self._assert_full_outside_hours_message(result["final_response"])

    def test_outside_hours_reservation_message_returns_objective_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("quero reservar", telefone="5511999990025")
        self.assertIn("fora do horário de atendimento para pedidos", result["final_response"])
        self.assertIn("Horários de atendimento:", result["final_response"])

    def test_outside_hours_order_message_returns_block_message(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("Quero pedir uma marmita", telefone="5511999990026")
        self.assertIn("fora do horário de atendimento para pedidos", result["final_response"])
        self.assertIn("Horários de atendimento:", result["final_response"])

    def test_outside_hours_hours_question_returns_direct_schedule(self) -> None:
        self._configure_outside_hours()
        result = self.orchestrator.handle_message("Qual o horário de funcionamento?", telefone="5511999990038")
        self.assertIn("Funcionamos nos seguintes horários:", result["final_response"])
        self.assertIn("* Segunda-feira: 9h às 12h30", result["final_response"])

    def test_inside_hours_menu_option_two_still_opens_cardapio(self) -> None:
        result = self.orchestrator.handle_message("2", telefone="5511999990019")
        self.assertIn("Cardápios disponíveis:", result["final_response"])

    def test_inside_hours_order_message_still_starts_order(self) -> None:
        result = self.orchestrator.handle_message("quero 2 marmitex", telefone="5511999990020")
        self.assertIn("Seu pedido ficou assim", result["final_response"])

    def test_order_offers_complements_before_delivery_choice(self) -> None:
        telefone = "5511999990061"
        self._enable_fake_complements()

        result = self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Deseja adicionar alguma bebida ou complemento?", result["final_response"])
        self.assertIn("1 - Água mineral: R$ 4,00", result["final_response"])
        self.assertIn("2 - Refrigerante lata: R$ 6,00", result["final_response"])
        self.assertIn("3 - Ovo adicional: R$ 2,50", result["final_response"])
        self.assertIn("5 - Não, obrigado", result["final_response"])
        self.assertNotIn("Você prefere:", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
        self.assertEqual(state.aguardando_resposta, "complemento")

    def test_active_dessert_without_price_is_not_listed_as_complement(self) -> None:
        fake_products = self._FakeQueryset(
            [
                SimpleNamespace(id=101, nome="Água mineral", preco=Decimal("4.00"), categoria="bebida"),
                SimpleNamespace(id=104, nome="Sobremesa do dia", preco=None, categoria="sobremesa"),
                SimpleNamespace(id=105, nome="Ovo adicional", preco=Decimal("2.50"), categoria="adicional"),
            ]
        )

        with patch("app.models.Produto.objects.filter", return_value=fake_products):
            options = self.orchestrator.order_agent._list_available_complements()

        product_names = [item["produto"] for item in options]
        self.assertIn("água mineral", product_names)
        self.assertIn("ovo adicional", product_names)
        self.assertNotIn("sobremesa do dia", product_names)

    def test_order_accepts_natural_language_complement_and_then_quantity(self) -> None:
        telefone = "5511999990062"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)

        updated = self.orchestrator.handle_message("quero uma água", telefone=telefone)
        state_after_qty = self._store[telefone]
        self.assertIn("Atualizei seu pedido", updated["final_response"])
        self.assertIn("* 2 marmitex individuais: R$ 42,00", updated["final_response"])
        self.assertIn("* 1 água mineral: R$ 4,00", updated["final_response"])
        self.assertIn("Total: R$ 46,00", updated["final_response"])
        self.assertIn("Deseja adicionar mais algum item?", updated["final_response"])
        self.assertEqual(state_after_qty.aguardando_resposta, "mais_complementos")

    def test_order_can_skip_complements_and_continue_to_delivery(self) -> None:
        telefone = "5511999990063"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)

        result = self.orchestrator.handle_message("não quero", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Você prefere:", result["final_response"])
        self.assertIn("1 - Entrega", result["final_response"])
        self.assertIn("2 - Retirada no local", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "tipo_entrega")

    def test_order_accepts_direct_complement_with_quantity_in_text(self) -> None:
        telefone = "5511999990064"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)

        updated = self.orchestrator.handle_message("quero 2 ovos adicionais", telefone=telefone)
        self.assertIn("* 2 marmitex individuais: R$ 42,00", updated["final_response"])
        self.assertIn("* 2 ovos adicionais: R$ 5,00", updated["final_response"])
        self.assertIn("Total: R$ 47,00", updated["final_response"])
        self.assertIn("Deseja adicionar mais algum item?", updated["final_response"])

        finish = self.orchestrator.handle_message("pode seguir", telefone=telefone)
        state = self._store[telefone]
        self.assertIn("Você prefere:", finish["final_response"])
        self.assertEqual(state.aguardando_resposta, "tipo_entrega")

    def test_order_accepts_two_soft_drinks_and_recalculates_total(self) -> None:
        telefone = "5511999990065"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        updated = self.orchestrator.handle_message("quero 2 refrigerantes", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("* 2 marmitex individuais: R$ 42,00", updated["final_response"])
        self.assertIn("* 2 refrigerante lata: R$ 12,00", updated["final_response"])
        self.assertIn("Total: R$ 54,00", updated["final_response"])
        self.assertIn("Deseja adicionar mais algum item?", updated["final_response"])
        self.assertEqual(state.aguardando_resposta, "mais_complementos")

    def test_family_marmita_accepts_two_extra_eggs_and_recalculates_total(self) -> None:
        telefone = "5511999990066"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 1 marmita para 3 pessoas", telefone=telefone)
        updated = self.orchestrator.handle_message("quero 2 ovos adicionais", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("* 1 marmita para 3 pessoas: R$ 85,00", updated["final_response"])
        self.assertIn("* 2 ovos adicionais: R$ 5,00", updated["final_response"])
        self.assertIn("Total: R$ 90,00", updated["final_response"])
        self.assertIn("Deseja adicionar mais algum item?", updated["final_response"])
        self.assertEqual(state.aguardando_resposta, "mais_complementos")

    def test_order_after_complement_can_follow_to_delivery(self) -> None:
        telefone = "5511999990067"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        self.orchestrator.handle_message("quero uma água", telefone=telefone)
        result = self.orchestrator.handle_message("não quero mais nada", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Você prefere:", result["final_response"])
        self.assertIn("1 - Entrega", result["final_response"])
        self.assertIn("2 - Retirada no local", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "tipo_entrega")

    def test_complement_step_numeric_one_selects_first_complement(self) -> None:
        telefone = "5511999990068"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Qual quantidade de água mineral você deseja adicionar?", result["final_response"])
        self.assertNotIn("Como posso ajudar?", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "quantidade_complemento")

    def test_complement_step_numeric_two_selects_second_complement(self) -> None:
        telefone = "5511999990069"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Qual quantidade de refrigerante lata você deseja adicionar?", result["final_response"])
        self.assertNotIn("retirada no local", result["final_response"].lower())
        self.assertEqual(state.aguardando_resposta, "quantidade_complemento")

    def test_complement_step_skip_phrases_continue_to_delivery(self) -> None:
        self._enable_fake_complements()

        scenarios = [
            ("5511999990070", "pode seguir"),
            ("5511999990071", "sem bebida"),
        ]
        for telefone, message in scenarios:
            with self.subTest(message=message):
                self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
                result = self.orchestrator.handle_message(message, telefone=telefone)
                state = self._store[telefone]

                self.assertIn("Você prefere:", result["final_response"])
                self.assertIn("1 - Entrega", result["final_response"])
                self.assertIn("2 - Retirada no local", result["final_response"])
                self.assertEqual(state.aguardando_resposta, "tipo_entrega")

    def test_order_quantity_message_preserves_additional_observation(self) -> None:
        telefone = "5511999990027"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        result = self.orchestrator.handle_message(
            "Uma só, porém quero acrescentar mais 1 bife",
            telefone=telefone,
        )
        state = self._store[telefone]

        self.assertIn("Seu pedido ficou assim", result["final_response"])
        self.assertIn("* Observação: acrescentar mais 1 bife", result["final_response"])
        self.assertIn("Total parcial: R$ 21,00", result["final_response"])
        self.assertIn("esse adicional pode ter cobrança extra", result["final_response"])
        self.assertEqual(state.itens_pedido[0]["observacao"], "acrescentar mais 1 bife")

    def test_additional_request_without_open_order_starts_order_naturally(self) -> None:
        result = self.orchestrator.handle_message("Pode acrescentar mais 1 bife?", telefone="5511999990028")

        self.assertIn("Posso registrar essa observação no seu pedido.", result["final_response"])
        self.assertIn("Você deseja:", result["final_response"])
        self.assertIn("Marmitex Individual", result["final_response"])

    def test_pickup_choice_after_five_minutes_keeps_order_context(self) -> None:
        telefone = "5511999990029"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)

        state_before = self._store[telefone]
        self.assertEqual(state_before.status_atendimento, AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
        self.assertEqual(state_before.aguardando_resposta, "tipo_entrega")

        state_before.atualizado_em = datetime.utcnow() - timedelta(minutes=5)

        result = self.orchestrator.handle_message("2", telefone=telefone)
        state_after = self._store[telefone]

        self.assertIn("retirada no local", result["final_response"].lower())
        self.assertNotIn("Cardápios disponíveis:", result["final_response"])
        self.assertNotIn("O cardápio", result["final_response"])
        self.assertEqual(state_after.tipo_entrega, "retirada")
        self.assertEqual(state_after.status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)
        self.assertEqual(state_after.aguardando_resposta, "nome_cliente")

    def test_beverage_question_during_delivery_choice_keeps_pending_step(self) -> None:
        telefone = "5511999990030"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)

        result = self.orchestrator.handle_message("Tem bebidas?", telefone=telefone)
        state_after = self._store[telefone]

        self.assertIn("bebidas ainda não estão cadastradas no sistema", result["final_response"])
        self.assertIn("Você prefere:", result["final_response"])
        self.assertIn("1 - Entrega", result["final_response"])
        self.assertIn("2 - Retirada no local", result["final_response"])
        self.assertNotIn("Cardápios disponíveis:", result["final_response"])
        self.assertNotIn("O cardápio", result["final_response"])
        self.assertEqual(state_after.status_atendimento, AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
        self.assertEqual(state_after.aguardando_resposta, "tipo_entrega")

    def test_beverage_question_variant_during_order_does_not_return_to_menu(self) -> None:
        telefone = "5511999990031"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)

        result = self.orchestrator.handle_message("Quero saber de bebidas! O que vc tem?", telefone=telefone)

        self.assertIn("bebidas ainda não estão cadastradas no sistema", result["final_response"])
        self.assertIn("Você prefere:", result["final_response"])
        self.assertNotIn("Como posso ajudar?", result["final_response"])

    def test_pickup_choice_after_beverage_question_still_works(self) -> None:
        telefone = "5511999990032"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)
        self.orchestrator.handle_message("Tem bebidas?", telefone=telefone)

        result = self.orchestrator.handle_message("2", telefone=telefone)
        state_after = self._store[telefone]

        self.assertIn("retirada no local", result["final_response"].lower())
        self.assertEqual(state_after.tipo_entrega, "retirada")
        self.assertEqual(state_after.status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)

    def test_beverage_question_during_payment_repeats_payment_step(self) -> None:
        telefone = "5511999990033"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("André", telefone=telefone)

        result = self.orchestrator.handle_message("Tem bebidas?", telefone=telefone)
        state_after = self._store[telefone]

        self.assertIn("bebidas ainda não estão cadastradas no sistema", result["final_response"])
        self.assertIn("Qual será a forma de pagamento?", result["final_response"])
        self.assertIn("1 - Pix", result["final_response"])
        self.assertIn("2 - Dinheiro", result["final_response"])
        self.assertIn("3 - Cartão", result["final_response"])
        self.assertEqual(state_after.status_atendimento, AtendimentoStatus.AGUARDANDO_PAGAMENTO)

    def test_order_continuation_prompt_uses_correct_accentuation(self) -> None:
        telefone = "5511999990034"
        self._store[telefone] = self._FakeState(
            telefone=telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_CONFIRMACAO,
            ultima_intencao="fazer_pedido",
            itens_pedido=[{"produto": "marmitex individual", "quantidade": 1, "subtotal": 21.0}],
            valor_total=21.0,
            forma_pagamento="Cartão",
            tipo_entrega="retirada",
        )

        result = self.orchestrator._order_continuation_prompt(self._store[telefone])

        self.assertIn("confirme se está tudo certo", result)
        self.assertNotIn("confirme se esta tudo certo", result)

    def test_pickup_flow_asks_name_before_payment(self) -> None:
        telefone = "5511999990043"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Duas", telefone=telefone)
        pickup = self.orchestrator.handle_message("2", telefone=telefone)
        state_after_pickup = self._store[telefone]

        self.assertIn("Qual nome devo colocar no pedido?", pickup["final_response"])
        self.assertEqual(state_after_pickup.status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)

        named = self.orchestrator.handle_message("André", telefone=telefone)
        state_after_name = self._store[telefone]

        self.assertIn("Obrigado, André", named["final_response"])
        self.assertIn("Forma de recebimento: retirada no local", named["final_response"])
        self.assertIn("Nome: André", named["final_response"])
        self.assertIn("Total: R$ 42,00", named["final_response"])
        self.assertIn("Qual será a forma de pagamento?", named["final_response"])
        self.assertEqual(state_after_name.status_atendimento, AtendimentoStatus.AGUARDANDO_PAGAMENTO)
        self.assertEqual(self._customer_names[telefone], "André")

    def test_delivery_flow_asks_address_then_name_then_payment(self) -> None:
        telefone = "5511999990044"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)
        delivery = self.orchestrator.handle_message("1", telefone=telefone)
        self.assertIn("Vou marcar como entrega", delivery["final_response"])
        self.assertIn("endereço completo para entrega", delivery["final_response"])

        named_prompt = self.orchestrator.handle_message("Rua Bahia 1000", telefone=telefone)
        state_after_address = self._store[telefone]
        self.assertIn("Qual nome devo colocar no pedido?", named_prompt["final_response"])
        self.assertEqual(state_after_address.status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)

        payment = self.orchestrator.handle_message("André", telefone=telefone)
        self.assertIn("Obrigado, André", payment["final_response"])
        self.assertIn("Forma de recebimento: entrega", payment["final_response"])
        self.assertIn("Endereço: Rua Bahia 1000", payment["final_response"])
        self.assertIn("Nome: André", payment["final_response"])
        self.assertIn("Qual será a forma de pagamento?", payment["final_response"])

    def test_new_order_keeps_previous_payment_proof_pending(self) -> None:
        telefone = "5511999990045"
        self._store[telefone] = self._FakeState(
            telefone=telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
            ultima_intencao="fazer_pedido",
            itens_pedido=[{"produto": "marmitex individual", "quantidade": 1, "subtotal": 21.0}],
            valor_total=21.0,
            forma_pagamento="Pix",
            aguardando_resposta="conferencia_pagamento",
        )

        result = self.orchestrator.handle_message("novo pedido", telefone=telefone)

        self.assertIn("Certo 😊 Vou iniciar um novo pedido.", result["final_response"])
        self.assertIn("continua aguardando conferência do comprovante pela equipe", result["final_response"])
        self.assertNotIn("conferencia do comprovante", result["final_response"])

    def test_invalid_state_with_pending_delivery_without_order_recovers_to_menu(self) -> None:
        telefone = "5511999990046"
        self._store[telefone] = self._FakeState(
            telefone=telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            ultima_intencao="fazer_pedido",
            aguardando_resposta="tipo_entrega",
        )

        result = self.orchestrator.handle_message("Oi", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Vamos recomeçar.", result["final_response"])
        self.assertIn("1 - Fazer pedido", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.INICIO)
        self.assertEqual(state.aguardando_resposta, "menu_principal")

    def test_menu_during_valid_order_asks_before_abandoning_flow(self) -> None:
        telefone = "5511999990047"
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)

        result = self.orchestrator.handle_message("menu", telefone=telefone)

        self.assertIn("Seu pedido ainda está em andamento", result["final_response"])
        self.assertIn("digite reiniciar", result["final_response"])
        self.assertIn("digite novo pedido", result["final_response"])

    def test_reiniciar_clears_invalid_state_and_restarts_attendance(self) -> None:
        telefone = "5511999990048"
        self._store[telefone] = self._FakeState(
            telefone=telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            ultima_intencao="fazer_pedido",
            aguardando_resposta="comprovante",
            forma_pagamento="",
        )

        result = self.orchestrator.handle_message("reiniciar", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Vamos recomeçar seu atendimento", result["final_response"])
        self.assertIn("1 - Fazer pedido", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.INICIO)
        self.assertEqual(state.aguardando_resposta, "menu_principal")

    def test_three_greetings_in_trapped_state_still_return_recovery_response(self) -> None:
        telefone = "5511999990049"
        self._store[telefone] = self._FakeState(
            telefone=telefone,
            status_atendimento="status_quebrado",
            ultima_intencao="fazer_pedido",
            aguardando_resposta="campo_desconhecido",
        )

        responses = [
            self.orchestrator.handle_message("Oi", telefone=telefone)["final_response"],
            self.orchestrator.handle_message("Oi", telefone=telefone)["final_response"],
            self.orchestrator.handle_message("Oi", telefone=telefone)["final_response"],
        ]

        self.assertTrue(any("Como posso ajudar?" in response for response in responses))
        self.assertTrue(all(response.strip() for response in responses))

    def test_service_returns_recovery_menu_when_orchestrator_raises_exception(self) -> None:
        services_module.orchestrator_agent.handle_message = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))

        response = services_module.gerar_resposta_atendimento("Oi", telefone="5511999990050")

        self.assertIn("Desculpe, tive uma dificuldade para continuar seu atendimento", response)
        self.assertIn("1 - Fazer pedido", response)

    def test_delivery_prompt_during_order_shows_only_today_hours(self) -> None:
        telefone = "5511999990042"
        original_localdate = orchestrator_module.timezone.localdate
        orchestrator_module.timezone.localdate = lambda: date(2026, 6, 3)

        try:
            self.orchestrator.handle_message("1", telefone=telefone)
            self.orchestrator.handle_message("1", telefone=telefone)
            result = self.orchestrator.handle_message("Uma só", telefone=telefone)
        finally:
            orchestrator_module.timezone.localdate = original_localdate

        self.assertIn("Você prefere:", result["final_response"])
        self.assertIn("Hoje, quarta-feira, entregas e retiradas acontecem das 11h às 13h.", result["final_response"])
        self.assertNotIn("segunda a sábado", result["final_response"])

    def test_pix_payment_instructions_include_total_key_and_payee(self) -> None:
        telefone = "5511999990039"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("André", telefone=telefone)
        result = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Pagamento via Pix", result["final_response"])
        self.assertIn("Valor do pedido: R$ 21,00", result["final_response"])
        self.assertIn("Chave Pix ainda não configurada no sistema.", result["final_response"])
        self.assertIn("Favorecido:\nMarmitaria da Adriana", result["final_response"])
        self.assertIn("envie o comprovante por aqui", result["final_response"])
        self.assertNotIn("Se quiser cancelar", result["final_response"])
        self.assertEqual(state.forma_pagamento, "Pix")
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_COMPROVANTE)

    def test_cash_payment_flow_still_reaches_order_confirmation(self) -> None:
        telefone = "5511999990072"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Duas", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("André", telefone=telefone)
        result = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Resumo do seu pedido:", result["final_response"])
        self.assertIn("Forma de pagamento: Dinheiro", result["final_response"])
        self.assertIn("Posso seguir com esse pedido?", result["final_response"])
        self.assertEqual(state.forma_pagamento, "Dinheiro")
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_CONFIRMACAO)

    def test_receipt_pending_ok_returns_short_response(self) -> None:
        telefone = "5511999990040"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("André", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        result = self.orchestrator.handle_message("Ok", telefone=telefone)

        self.assertIn("Fico aguardando o comprovante por aqui", result["final_response"])
        self.assertNotIn("Se quiser cancelar", result["final_response"])
        self.assertNotIn("Pagamento via Pix", result["final_response"])

    def test_final_confirmation_accepts_pode_sim(self) -> None:
        telefone = "5511999990056"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Duas", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("Andre", telefone=telefone)
        self.orchestrator.handle_message("3", telefone=telefone)
        result = self.orchestrator.handle_message("Pode sim", telefone=telefone)

        self.assertIn("Pedido confirmado com sucesso", result["final_response"])
        self.assertIn("Forma de pagamento: Cartão", result["final_response"])
        self.assertIn("informe o nome Andre para retirar", result["final_response"])

    def test_final_confirmation_accepts_pode(self) -> None:
        telefone = "5511999990057"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Duas", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("Andre", telefone=telefone)
        self.orchestrator.handle_message("3", telefone=telefone)
        result = self.orchestrator.handle_message("Pode", telefone=telefone)

        self.assertIn("Pedido confirmado com sucesso", result["final_response"])

    def test_final_confirmation_accepts_ok(self) -> None:
        telefone = "5511999990058"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Duas", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("Andre", telefone=telefone)
        self.orchestrator.handle_message("3", telefone=telefone)
        result = self.orchestrator.handle_message("Ok", telefone=telefone)

        self.assertIn("Pedido confirmado com sucesso", result["final_response"])

    def test_final_confirmation_accepts_confirmo(self) -> None:
        telefone = "5511999990059"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Duas", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("Andre", telefone=telefone)
        self.orchestrator.handle_message("3", telefone=telefone)
        result = self.orchestrator.handle_message("Confirmo", telefone=telefone)

        self.assertIn("Pedido confirmado com sucesso", result["final_response"])

    def test_final_confirmation_cancel_clears_order(self) -> None:
        telefone = "5511999990060"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Duas", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("Andre", telefone=telefone)
        self.orchestrator.handle_message("3", telefone=telefone)
        result = self.orchestrator.handle_message("Cancelar", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Pedido cancelado", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.INICIO)
        self.assertEqual(state.itens_pedido, [])

    def test_receipt_pending_cancel_clears_order_state(self) -> None:
        telefone = "5511999990041"

        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        self.orchestrator.handle_message("Uma só", telefone=telefone)
        self.orchestrator.handle_message("2", telefone=telefone)
        self.orchestrator.handle_message("André", telefone=telefone)
        self.orchestrator.handle_message("1", telefone=telefone)
        result = self.orchestrator.handle_message("Cancelar", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Pedido cancelado", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.INICIO)
        self.assertEqual(state.itens_pedido, [])
        self.assertEqual(state.forma_pagamento, "")

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
        self.assertIn("informações básicas, como horário, entrega, localização e cardápio", response)

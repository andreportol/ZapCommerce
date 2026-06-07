from app.agents.conversation_state import AtendimentoStatus

from .base import ConversationFlowBaseTestCase


class OrderFlowEndToEndTests(ConversationFlowBaseTestCase):
    def test_end_to_end_two_marmitex_no_complement_pickup_name_and_pix(self) -> None:
        telefone = "5511999992201"
        self._enable_fake_complements()

        first = self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        second = self.orchestrator.handle_message("não quero", telefone=telefone)
        third = self.orchestrator.handle_message("2", telefone=telefone)
        fourth = self.orchestrator.handle_message("André", telefone=telefone)
        fifth = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Deseja adicionar alguma bebida ou complemento?", first["final_response"])
        self._assert_delivery_prompt(second["final_response"])
        self.assertIn("retirada no local", third["final_response"].lower())
        self.assertIn("Qual será a forma de pagamento?", fourth["final_response"])
        self.assertIn("Pix", fifth["final_response"])
        self.assertIn("comprovante", fifth["final_response"].lower())
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_COMPROVANTE)
        self.assertEqual(state.aguardando_resposta, "comprovante")
        self.assertEqual(state.valor_total, 42.0)

    def test_end_to_end_two_marmitex_with_water_pickup_name_and_pix(self) -> None:
        telefone = "5511999992202"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        second = self.orchestrator.handle_message("quero uma água", telefone=telefone)
        third = self.orchestrator.handle_message("não quero mais nada", telefone=telefone)
        fourth = self.orchestrator.handle_message("2", telefone=telefone)
        fifth = self.orchestrator.handle_message("André", telefone=telefone)
        sixth = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("* 1 água mineral: R$ 4,00", second["final_response"])
        self.assertIn("Total: R$ 46,00", second["final_response"])
        self._assert_delivery_prompt(third["final_response"])
        self.assertIn("Qual será a forma de pagamento?", fifth["final_response"])
        self.assertIn("Pix", sixth["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_COMPROVANTE)
        self.assertEqual(state.valor_total, 46.0)

    def test_end_to_end_marmita_three_people_with_two_soft_drinks_delivery_and_cash(self) -> None:
        telefone = "5511999992203"
        self._enable_fake_complements()

        first = self.orchestrator.handle_message("quero 1 marmita para 3 pessoas", telefone=telefone)
        second = self.orchestrator.handle_message("quero 2 refrigerantes", telefone=telefone)
        third = self.orchestrator.handle_message("não quero mais nada", telefone=telefone)
        fourth = self.orchestrator.handle_message("1", telefone=telefone)
        fifth = self.orchestrator.handle_message("Rua das Flores, 123", telefone=telefone)
        sixth = self.orchestrator.handle_message("André", telefone=telefone)
        seventh = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Deseja adicionar alguma bebida ou complemento?", first["final_response"])
        self.assertIn("* 2 refrigerante lata: R$ 12,00", second["final_response"])
        self.assertIn("* 1 marmita para 3 pessoas: R$ 85,00", second["final_response"])
        self.assertIn("Total: R$ 97,00", second["final_response"])
        self._assert_delivery_prompt(third["final_response"])
        self.assertIn("informe o endereço completo", fourth["final_response"])
        self.assertIn("Endereço anotado", fifth["final_response"])
        self.assertIn("Qual será a forma de pagamento?", sixth["final_response"])
        self.assertIn("Forma de pagamento: Dinheiro", seventh["final_response"])
        self.assertIn("Posso seguir com esse pedido?", seventh["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_CONFIRMACAO)
        self.assertEqual(state.aguardando_resposta, "confirmacao")
        self.assertEqual(state.tipo_entrega, "entrega")
        self.assertEqual(state.valor_total, 97.0)

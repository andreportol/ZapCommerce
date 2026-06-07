from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.conversation_state import AtendimentoStatus

from .base import ConversationFlowBaseTestCase


class ComplementsFlowTests(ConversationFlowBaseTestCase):
    class _FakeQueryset(list):
        def order_by(self, *_args, **_kwargs):
            return self

    def test_two_marmitex_skip_complements_goes_to_delivery(self) -> None:
        telefone = "5511999992101"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("não quero", telefone=telefone)
        state = self._store[telefone]

        self._assert_delivery_prompt(result["final_response"])
        self.assertEqual(state.aguardando_resposta, "tipo_entrega")

    def test_two_marmitex_adds_one_water_and_asks_for_more_items(self) -> None:
        telefone = "5511999992102"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("quero uma água", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("* 2 marmitex individuais: R$ 42,00", result["final_response"])
        self.assertIn("* 1 água mineral: R$ 4,00", result["final_response"])
        self.assertIn("Total: R$ 46,00", result["final_response"])
        self.assertIn("Deseja adicionar mais algum item?", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "mais_complementos")

    def test_two_marmitex_adds_two_soft_drinks_and_recalculates_total(self) -> None:
        telefone = "5511999992103"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("quero 2 refrigerantes", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("* 2 refrigerante lata: R$ 12,00", result["final_response"])
        self.assertIn("Total: R$ 54,00", result["final_response"])
        self.assertIn("Deseja adicionar mais algum item?", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "mais_complementos")

    def test_marmita_for_three_people_adds_two_extra_eggs(self) -> None:
        telefone = "5511999992104"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 1 marmita para 3 pessoas", telefone=telefone)
        result = self.orchestrator.handle_message("quero 2 ovos adicionais", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("* 1 marmita para 3 pessoas: R$ 85,00", result["final_response"])
        self.assertIn("* 2 ovos adicionais: R$ 5,00", result["final_response"])
        self.assertIn("Total: R$ 90,00", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "mais_complementos")

    def test_after_adding_complement_not_wanting_more_goes_to_delivery(self) -> None:
        telefone = "5511999992105"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        self.orchestrator.handle_message("quero uma água", telefone=telefone)
        result = self.orchestrator.handle_message("não quero mais nada", telefone=telefone)
        state = self._store[telefone]

        self._assert_delivery_prompt(result["final_response"])
        self.assertEqual(state.aguardando_resposta, "tipo_entrega")

    def test_skip_phrases_do_not_add_complements(self) -> None:
        self._enable_fake_complements()

        scenarios = [
            ("5511999992106", "sem bebida"),
            ("5511999992107", "pode seguir"),
        ]
        for telefone, message in scenarios:
            with self.subTest(message=message):
                self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
                result = self.orchestrator.handle_message(message, telefone=telefone)
                state = self._store[telefone]

                self._assert_delivery_prompt(result["final_response"])
                self.assertEqual(state.aguardando_resposta, "tipo_entrega")
                self.assertEqual(state.valor_total, 42.0)

    def test_active_dessert_without_price_is_not_listed_or_calculated(self) -> None:
        fake_products = self._FakeQueryset(
            [
                SimpleNamespace(id=101, nome="Água mineral", preco=Decimal("4.00"), categoria="bebida"),
                SimpleNamespace(id=104, nome="Sobremesa do dia", preco=None, categoria="sobremesa"),
                SimpleNamespace(id=105, nome="Ovo adicional", preco=Decimal("2.50"), categoria="adicional"),
            ]
        )

        with patch("app.models.Produto.objects.filter", return_value=fake_products):
            options = self.orchestrator.order_agent._list_available_complements()

        self.assertEqual([item["produto"] for item in options], ["água mineral", "ovo adicional"])
        self.assertNotIn("sobremesa do dia", [item["produto"] for item in options])
        self.assertTrue(all(item["valor_unitario"] > 0 for item in options))

    def test_complements_are_offered_before_delivery(self) -> None:
        telefone = "5511999992108"
        self._enable_fake_complements()

        result = self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Deseja adicionar alguma bebida ou complemento?", result["final_response"])
        self.assertNotIn("Você prefere:", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
        self.assertEqual(state.aguardando_resposta, "complemento")

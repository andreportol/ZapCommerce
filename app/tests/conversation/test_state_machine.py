from app.conversation.state_machine import ConversationStateMachine
from app.conversation.states import AwaitingResponse

from .base import ConversationFlowBaseTestCase


class ConversationStateMachineTests(ConversationFlowBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.state_machine = ConversationStateMachine()

    def test_menu_principal_one_goes_to_produto(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.MENU_PRINCIPAL.value, "1"),
            AwaitingResponse.PRODUTO.value,
        )

    def test_produto_one_goes_to_quantidade(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.PRODUTO.value, "1"),
            AwaitingResponse.QUANTIDADE.value,
        )

    def test_quantidade_two_goes_to_complemento(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.QUANTIDADE.value, "2"),
            AwaitingResponse.COMPLEMENTO.value,
        )

    def test_complemento_nao_quero_goes_to_tipo_entrega(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.COMPLEMENTO.value, "não quero"),
            AwaitingResponse.TIPO_ENTREGA.value,
        )

    def test_complemento_quero_uma_agua_goes_to_mais_complementos(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.COMPLEMENTO.value, "quero uma água"),
            AwaitingResponse.MAIS_COMPLEMENTOS.value,
        )

    def test_mais_complementos_nao_quero_mais_nada_goes_to_tipo_entrega(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.MAIS_COMPLEMENTOS.value, "não quero mais nada"),
            AwaitingResponse.TIPO_ENTREGA.value,
        )

    def test_tipo_entrega_two_goes_to_nome_cliente(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.TIPO_ENTREGA.value, "2"),
            AwaitingResponse.NOME_CLIENTE.value,
        )

    def test_tipo_entrega_one_goes_to_endereco(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.TIPO_ENTREGA.value, "1"),
            AwaitingResponse.ENDERECO.value,
        )

    def test_endereco_goes_to_nome_cliente(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.ENDERECO.value, "Rua Bahia 1000"),
            AwaitingResponse.NOME_CLIENTE.value,
        )

    def test_nome_cliente_goes_to_forma_pagamento(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.NOME_CLIENTE.value, "André"),
            AwaitingResponse.FORMA_PAGAMENTO.value,
        )

    def test_forma_pagamento_one_goes_to_comprovante(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.FORMA_PAGAMENTO.value, "1"),
            AwaitingResponse.COMPROVANTE.value,
        )

    def test_forma_pagamento_two_goes_to_confirmacao(self) -> None:
        self.assertEqual(
            self.state_machine.get_expected_next_awaiting_response(AwaitingResponse.FORMA_PAGAMENTO.value, "2"),
            AwaitingResponse.CONFIRMACAO.value,
        )

    def test_unknown_transition_returns_not_mapped(self) -> None:
        explanation = self.state_machine.explain_transition(AwaitingResponse.COMPROVANTE.value, "oi")

        self.assertFalse(explanation.matched)
        self.assertEqual(explanation.expected_next_awaiting_response, AwaitingResponse.NOT_MAPPED.value)
        self.assertIn("não mapeada", explanation.description.lower())

    def test_is_transition_allowed_uses_expected_mapping(self) -> None:
        self.assertTrue(
            self.state_machine.is_transition_allowed(
                AwaitingResponse.TIPO_ENTREGA.value,
                "2",
                AwaitingResponse.NOME_CLIENTE.value,
            )
        )

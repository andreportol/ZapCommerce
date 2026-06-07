from app.agents.conversation_state import AtendimentoStatus

from .base import ConversationFlowBaseTestCase
from .snapshots import build_conversation_snapshot, format_conversation_snapshot


class GoldenConversationTests(ConversationFlowBaseTestCase):
    def test_golden_two_marmitex_no_complement_pickup_and_pix(self) -> None:
        telefone = "5511999992301"
        self._enable_fake_complements()

        history = self._run_conversation(
            telefone=telefone,
            messages=["oi", "1", "1", "2", "não quero", "2", "André", "1"],
        )
        snapshot = build_conversation_snapshot(history)
        snapshot_text = format_conversation_snapshot(snapshot)
        final_state = self._store[telefone]

        self.assertIn("Como posso ajudar", history[0].bot_response, snapshot_text)
        self.assertEqual(history[0].aguardando_resposta, "menu_principal")
        contract = self._assert_contract_matches_step(history[0])
        self.assertEqual(contract.next_state, "")
        self.assertEqual(contract.awaiting_response, "")

        self.assertIn("Você deseja:", history[1].bot_response, snapshot_text)
        self.assertEqual(history[1].status_atendimento, AtendimentoStatus.AGUARDANDO_PRODUTO)
        self._assert_contract_matches_step(
            history[1],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_produto",
        )
        self._assert_state_machine_transition(history[1])

        self.assertIn("Quantas marmitex individuais você deseja?", history[2].bot_response, snapshot_text)
        self.assertEqual(history[2].status_atendimento, AtendimentoStatus.AGUARDANDO_QUANTIDADE)
        self.assertEqual(history[2].aguardando_resposta, "quantidade")
        self._assert_contract_matches_step(
            history[2],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_quantidade",
            expected_awaiting_response="quantidade",
        )
        self._assert_state_machine_transition(history[2])

        self.assertIn("Deseja adicionar alguma bebida ou complemento?", history[3].bot_response, snapshot_text)
        self.assertEqual(history[3].valor_total, 42.0)
        self.assertEqual(history[3].aguardando_resposta, "complemento")
        self._assert_contract_matches_step(
            history[3],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="complemento",
        )
        self._assert_state_machine_transition(history[3])

        self._assert_delivery_prompt(history[4].bot_response)
        self.assertEqual(history[4].valor_total, 42.0)
        self.assertEqual(len(history[4].itens_pedido), 1)
        self.assertEqual(history[4].aguardando_resposta, "tipo_entrega")
        self._assert_contract_matches_step(
            history[4],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="tipo_entrega",
        )
        self._assert_state_machine_transition(history[4])

        self.assertIn("Qual nome devo colocar no pedido?", history[5].bot_response, snapshot_text)
        self.assertEqual(history[5].tipo_entrega, "retirada")
        self.assertEqual(history[5].status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)
        self._assert_contract_matches_step(
            history[5],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_nome_cliente",
            expected_awaiting_response="nome_cliente",
        )
        self._assert_state_machine_transition(history[5])

        self.assertIn("Qual será a forma de pagamento?", history[6].bot_response, snapshot_text)
        self.assertIn("André", history[6].bot_response)
        self.assertEqual(history[6].status_atendimento, AtendimentoStatus.AGUARDANDO_PAGAMENTO)
        self._assert_contract_matches_step(
            history[6],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_pagamento",
            expected_awaiting_response="forma_pagamento",
        )
        self._assert_state_machine_transition(history[6])

        self.assertIn("Chave Pix", history[7].bot_response, snapshot_text)
        self.assertEqual(history[7].forma_pagamento, "Pix")
        self._assert_contract_matches_step(
            history[7],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_comprovante",
            expected_awaiting_response="comprovante",
            expected_payment_updated=True,
        )
        self._assert_state_machine_transition(history[7])
        self.assertEqual(final_state.valor_total, 42.0)
        self.assertEqual(final_state.status_atendimento, AtendimentoStatus.AGUARDANDO_COMPROVANTE)
        self.assertEqual(final_state.aguardando_resposta, "comprovante")

    def test_golden_two_marmitex_with_water_pickup_and_pix(self) -> None:
        telefone = "5511999992302"
        self._enable_fake_complements()

        history = self._run_conversation(
            telefone=telefone,
            messages=["oi", "1", "1", "2", "quero uma água", "não quero mais nada", "2", "André", "1"],
        )
        snapshot = build_conversation_snapshot(history)
        snapshot_text = format_conversation_snapshot(snapshot)
        final_state = self._store[telefone]

        self.assertIn("Deseja adicionar", history[3].bot_response, snapshot_text)
        self.assertIn("Água mineral", history[3].bot_response, snapshot_text)
        self._assert_contract_matches_step(
            history[3],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="complemento",
        )

        self.assertIn("* 1 água mineral: R$ 4,00", history[4].bot_response, snapshot_text)
        self.assertIn("Total: R$ 46,00", history[4].bot_response, snapshot_text)
        self.assertIn("Deseja adicionar mais algum item?", history[4].bot_response, snapshot_text)
        self.assertEqual(history[4].aguardando_resposta, "mais_complementos")
        self._assert_contract_matches_step(
            history[4],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="mais_complementos",
        )
        self._assert_state_machine_transition(history[4])

        self._assert_delivery_prompt(history[5].bot_response)
        self.assertEqual(history[5].valor_total, 46.0)
        self._assert_contract_matches_step(
            history[5],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="tipo_entrega",
        )
        self._assert_state_machine_transition(history[5])

        self.assertIn("Qual nome devo colocar no pedido?", history[6].bot_response, snapshot_text)
        self.assertEqual(history[6].tipo_entrega, "retirada")
        self._assert_contract_matches_step(
            history[6],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_nome_cliente",
            expected_awaiting_response="nome_cliente",
        )
        self._assert_state_machine_transition(history[6])

        self.assertIn("Qual será a forma de pagamento?", history[7].bot_response, snapshot_text)
        self._assert_contract_matches_step(
            history[7],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_pagamento",
            expected_awaiting_response="forma_pagamento",
        )
        self._assert_state_machine_transition(history[7])
        self.assertIn("Chave Pix", history[8].bot_response, snapshot_text)
        self._assert_contract_matches_step(
            history[8],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_comprovante",
            expected_awaiting_response="comprovante",
            expected_payment_updated=True,
        )
        self._assert_state_machine_transition(history[8])
        self.assertEqual(final_state.valor_total, 46.0)
        self.assertEqual(final_state.forma_pagamento, "Pix")
        self.assertEqual(final_state.status_atendimento, AtendimentoStatus.AGUARDANDO_COMPROVANTE)

    def test_golden_marmita_three_people_with_two_soft_drinks_delivery_name_and_cash(self) -> None:
        telefone = "5511999992303"
        self._enable_fake_complements()

        history = self._run_conversation(
            telefone=telefone,
            messages=[
                "oi",
                "1",
                "marmita para 3 pessoas",
                "quero 2 refrigerantes",
                "não quero mais nada",
                "1",
                "Rua Bahia 1000",
                "André",
                "2",
            ],
        )
        snapshot = build_conversation_snapshot(history)
        snapshot_text = format_conversation_snapshot(snapshot)
        final_state = self._store[telefone]

        self.assertIn("* 1 marmita para 3 pessoas: R$ 85,00", history[2].bot_response, snapshot_text)
        self.assertIn("Deseja adicionar alguma bebida ou complemento?", history[2].bot_response, snapshot_text)
        self.assertEqual(history[2].valor_total, 85.0)
        self._assert_contract_matches_step(
            history[2],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="complemento",
        )
        self._assert_state_machine_transition(history[2])

        self.assertIn("* 2 refrigerante lata: R$ 12,00", history[3].bot_response, snapshot_text)
        self.assertIn("Total: R$ 97,00", history[3].bot_response, snapshot_text)
        self.assertEqual(history[3].aguardando_resposta, "mais_complementos")
        self._assert_contract_matches_step(
            history[3],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="mais_complementos",
        )
        self._assert_state_machine_transition(history[3])

        self._assert_delivery_prompt(history[4].bot_response)
        self.assertEqual(history[4].valor_total, 97.0)
        self._assert_contract_matches_step(
            history[4],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="tipo_entrega",
        )
        self._assert_state_machine_transition(history[4])

        self.assertIn("informe o endereço completo", history[5].bot_response, snapshot_text)
        self.assertEqual(history[5].tipo_entrega, "entrega")
        self.assertEqual(history[5].status_atendimento, AtendimentoStatus.AGUARDANDO_ENDERECO)
        self._assert_contract_matches_step(
            history[5],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_endereco",
            expected_awaiting_response="endereco",
        )
        self._assert_state_machine_transition(history[5])

        self.assertIn("Endereço anotado", history[6].bot_response, snapshot_text)
        self.assertIn("Qual nome devo colocar no pedido?", history[6].bot_response, snapshot_text)
        self.assertEqual(history[6].status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)
        self._assert_contract_matches_step(
            history[6],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_nome_cliente",
            expected_awaiting_response="nome_cliente",
        )
        self._assert_state_machine_transition(history[6])

        self.assertIn("Qual será a forma de pagamento?", history[7].bot_response, snapshot_text)
        self.assertIn("André", history[7].bot_response, snapshot_text)
        self.assertEqual(history[7].status_atendimento, AtendimentoStatus.AGUARDANDO_PAGAMENTO)
        self._assert_contract_matches_step(
            history[7],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_pagamento",
            expected_awaiting_response="forma_pagamento",
        )
        self._assert_state_machine_transition(history[7])

        self.assertIn("Forma de pagamento: Dinheiro", history[8].bot_response, snapshot_text)
        self.assertIn("Posso seguir com esse pedido?", history[8].bot_response, snapshot_text)
        self.assertNotIn("Chave Pix", history[8].bot_response)
        self._assert_contract_matches_step(
            history[8],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_confirmacao",
            expected_awaiting_response="confirmacao",
            expected_payment_updated=True,
        )
        self._assert_state_machine_transition(history[8])
        self.assertEqual(final_state.valor_total, 97.0)
        self.assertEqual(final_state.tipo_entrega, "entrega")
        self.assertEqual(final_state.forma_pagamento, "Dinheiro")
        self.assertEqual(final_state.status_atendimento, AtendimentoStatus.AGUARDANDO_CONFIRMACAO)

    def test_golden_two_marmitex_with_natural_complement_refusal(self) -> None:
        telefone = "5511999992304"
        self._enable_fake_complements()

        history = self._run_conversation(
            telefone=telefone,
            messages=["oi", "1", "1", "2", "sem bebida"],
        )
        snapshot = build_conversation_snapshot(history)
        snapshot_text = format_conversation_snapshot(snapshot)
        final_state = self._store[telefone]

        self.assertIn("Deseja adicionar alguma bebida ou complemento?", history[3].bot_response, snapshot_text)
        self._assert_delivery_prompt(history[4].bot_response)
        self.assertEqual(history[4].valor_total, 42.0)
        self.assertEqual(len(history[4].itens_pedido), 1)
        self._assert_contract_matches_step(
            history[4],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_tipo_entrega",
            expected_awaiting_response="tipo_entrega",
        )
        self._assert_state_machine_transition(history[4])
        self.assertEqual(final_state.aguardando_resposta, "tipo_entrega")

    def test_golden_numeric_ambiguity_uses_contextual_states(self) -> None:
        telefone = "5511999992305"
        self._enable_fake_complements()

        history = self._run_conversation(
            telefone=telefone,
            messages=["oi", "1", "1", "2", "não quero", "2", "André", "1"],
        )
        snapshot = build_conversation_snapshot(history)
        snapshot_text = format_conversation_snapshot(snapshot)

        self.assertEqual(history[0].aguardando_resposta, "menu_principal", snapshot_text)
        self.assertEqual(history[1].status_atendimento, AtendimentoStatus.AGUARDANDO_PRODUTO, snapshot_text)
        self.assertEqual(history[2].status_atendimento, AtendimentoStatus.AGUARDANDO_QUANTIDADE, snapshot_text)
        self.assertEqual(history[2].aguardando_resposta, "quantidade", snapshot_text)
        self.assertEqual(history[3].aguardando_resposta, "complemento", snapshot_text)
        self.assertEqual(history[4].aguardando_resposta, "tipo_entrega", snapshot_text)
        self.assertEqual(history[5].status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE, snapshot_text)
        self.assertEqual(history[6].status_atendimento, AtendimentoStatus.AGUARDANDO_PAGAMENTO, snapshot_text)
        self.assertEqual(history[7].status_atendimento, AtendimentoStatus.AGUARDANDO_COMPROVANTE, snapshot_text)
        self._assert_contract_matches_step(
            history[7],
            expected_intent="fazer_pedido",
            expected_next_state="aguardando_comprovante",
            expected_awaiting_response="comprovante",
            expected_payment_updated=True,
        )

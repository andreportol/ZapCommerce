from app.agents.conversation_state import AtendimentoStatus

from .base import ConversationFlowBaseTestCase


class NumericAmbiguityTests(ConversationFlowBaseTestCase):
    def test_menu_principal_one_starts_order(self) -> None:
        telefone = "5511999992001"
        self._set_state(
            telefone,
            status_atendimento=AtendimentoStatus.INICIO,
            aguardando_resposta="menu_principal",
            ultima_intencao="menu_principal",
        )

        result = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Perfeito", result["final_response"])
        self.assertIn("Você deseja:", result["final_response"])
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_PRODUTO)
        self.assertEqual(state.ultima_intencao, "fazer_pedido")

    def test_menu_principal_two_opens_cardapio(self) -> None:
        telefone = "5511999992002"
        self._set_state(
            telefone,
            status_atendimento=AtendimentoStatus.INICIO,
            aguardando_resposta="menu_principal",
            ultima_intencao="menu_principal",
        )

        result = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Cardápios disponíveis:", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "dia_cardapio")
        self.assertEqual(state.ultima_intencao, "consultar_cardapio")

    def test_tipo_entrega_one_means_delivery(self) -> None:
        telefone = "5511999992003"
        self._set_state(
            telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            aguardando_resposta="tipo_entrega",
            ultima_intencao="fazer_pedido",
            itens_pedido=self._build_main_item(),
            produto="marmitex_individual",
            quantidade=2,
            valor_unitario=21.0,
            valor_total=42.0,
        )

        result = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Vou marcar como entrega", result["final_response"])
        self.assertIn("informe o endereço completo", result["final_response"])
        self.assertEqual(state.tipo_entrega, "entrega")
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_ENDERECO)
        self.assertEqual(state.aguardando_resposta, "endereco")

    def test_tipo_entrega_two_means_pickup(self) -> None:
        telefone = "5511999992004"
        self._set_state(
            telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            aguardando_resposta="tipo_entrega",
            ultima_intencao="fazer_pedido",
            itens_pedido=self._build_main_item(),
            produto="marmitex_individual",
            quantidade=2,
            valor_unitario=21.0,
            valor_total=42.0,
        )

        result = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("retirada no local", result["final_response"].lower())
        self.assertIn("Qual nome devo colocar no pedido?", result["final_response"])
        self.assertEqual(state.tipo_entrega, "retirada")
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)
        self.assertEqual(state.aguardando_resposta, "nome_cliente")

    def test_forma_pagamento_one_means_pix(self) -> None:
        telefone = "5511999992005"
        self._customer_names[telefone] = "André"
        self._set_state(
            telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            aguardando_resposta="forma_pagamento",
            ultima_intencao="fazer_pedido",
            tipo_entrega="retirada",
            endereco="retirada no local",
            itens_pedido=self._build_main_item(),
            produto="marmitex_individual",
            quantidade=2,
            valor_unitario=21.0,
            valor_total=42.0,
        )

        result = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Pix", result["final_response"])
        self.assertIn("comprovante", result["final_response"].lower())
        self.assertEqual(state.forma_pagamento, "Pix")
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_COMPROVANTE)
        self.assertEqual(state.aguardando_resposta, "comprovante")

    def test_forma_pagamento_two_means_cash(self) -> None:
        telefone = "5511999992006"
        self._customer_names[telefone] = "André"
        self._set_state(
            telefone,
            status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            aguardando_resposta="forma_pagamento",
            ultima_intencao="fazer_pedido",
            tipo_entrega="retirada",
            endereco="retirada no local",
            itens_pedido=self._build_main_item(),
            produto="marmitex_individual",
            quantidade=2,
            valor_unitario=21.0,
            valor_total=42.0,
        )

        result = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Forma de pagamento: Dinheiro", result["final_response"])
        self.assertIn("Posso seguir com esse pedido?", result["final_response"])
        self.assertEqual(state.forma_pagamento, "Dinheiro")
        self.assertEqual(state.status_atendimento, AtendimentoStatus.AGUARDANDO_CONFIRMACAO)
        self.assertEqual(state.aguardando_resposta, "confirmacao")

    def test_complement_one_means_first_available_complement(self) -> None:
        telefone = "5511999992007"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("1", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Qual quantidade de água mineral você deseja adicionar?", result["final_response"])
        self.assertNotIn("Como posso ajudar?", result["final_response"])
        self.assertEqual(state.aguardando_resposta, "quantidade_complemento")

    def test_complement_two_means_second_available_complement(self) -> None:
        telefone = "5511999992008"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("2", telefone=telefone)
        state = self._store[telefone]

        self.assertIn("Qual quantidade de refrigerante lata você deseja adicionar?", result["final_response"])
        self.assertNotIn("retirada no local", result["final_response"].lower())
        self.assertEqual(state.aguardando_resposta, "quantidade_complemento")

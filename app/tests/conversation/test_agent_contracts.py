from app.agents.message_agent import MessageAnalysis
from app.conversation.contracts import AgentResponseContract

from .base import ConversationFlowBaseTestCase


class AgentContractsTests(ConversationFlowBaseTestCase):
    def test_contract_from_simple_order_response_preserves_message(self) -> None:
        payload = {
            "state": {
                "status_atendimento": "aguardando_tipo_entrega",
                "aguardando_resposta": "complemento",
            },
            "response": "Deseja adicionar alguma bebida ou complemento?",
        }

        contract = AgentResponseContract.from_order_agent_response(payload)

        self.assertTrue(contract.success)
        self.assertEqual(contract.message, "Deseja adicionar alguma bebida ou complemento?")
        self.assertEqual(contract.raw_response, payload)

    def test_contract_preserves_raw_response(self) -> None:
        payload = {
            "final_response": "Olá!",
            "intent": "saudacao",
            "database": {"implemented": False},
        }

        contract = AgentResponseContract.from_orchestrator_response(payload)

        self.assertIs(contract.raw_response, payload)
        self.assertEqual(contract.message, "Olá!")

    def test_contract_accepts_missing_optional_fields(self) -> None:
        contract = AgentResponseContract.from_order_agent_response({"response": "Tudo certo"})

        self.assertTrue(contract.success)
        self.assertEqual(contract.message, "Tudo certo")
        self.assertEqual(contract.next_state, "")
        self.assertEqual(contract.awaiting_response, "")
        self.assertEqual(contract.errors, [])

    def test_contract_marks_failure_when_errors_are_explicit(self) -> None:
        payload = {
            "success": False,
            "response": "Falhou",
            "errors": ["invalid_step"],
        }

        contract = AgentResponseContract.from_order_agent_response(payload)

        self.assertFalse(contract.success)
        self.assertEqual(contract.errors, ["invalid_step"])

    def test_contract_does_not_change_original_message(self) -> None:
        payload = {
            "final_response": "Perfeito 😊 Pagamento via Pix.",
            "intent": "fazer_pedido",
        }

        contract = AgentResponseContract.from_orchestrator_response(payload)

        self.assertEqual(contract.message, payload["final_response"])

    def test_contract_does_not_change_real_flow_state(self) -> None:
        telefone = "5511999992401"
        self._enable_fake_complements()

        self.orchestrator.handle_message("quero 2 marmitex", telefone=telefone)
        result = self.orchestrator.handle_message("não quero", telefone=telefone)
        before = self._store[telefone]
        snapshot = (before.status_atendimento, before.aguardando_resposta, before.valor_total)

        contract = AgentResponseContract.from_orchestrator_response(
            {
                "intent": "fazer_pedido",
                "final_response": result["final_response"],
                "order_state": before.__dict__.copy(),
            }
        )
        after = self._store[telefone]

        self.assertEqual(snapshot, (after.status_atendimento, after.aguardando_resposta, after.valor_total))
        self.assertEqual(contract.next_state, before.status_atendimento)
        self.assertEqual(contract.awaiting_response, before.aguardando_resposta)

    def test_contract_represents_next_state_and_awaiting_response(self) -> None:
        payload = {
            "state": {
                "status_atendimento": "aguardando_pagamento",
                "aguardando_resposta": "forma_pagamento",
            },
            "response": "Qual será a forma de pagamento?",
        }

        contract = AgentResponseContract.from_order_agent_response(payload)

        self.assertEqual(contract.next_state, "aguardando_pagamento")
        self.assertEqual(contract.awaiting_response, "forma_pagamento")

    def test_contract_represents_requires_human(self) -> None:
        payload = {
            "state": {
                "status_atendimento": "encaminhar_atendente",
                "aguardando_resposta": "consulta_proprietaria",
            },
            "pricing": {"needs_owner": True},
            "response": "Vou consultar a proprietária.",
        }

        contract = AgentResponseContract.from_order_agent_response(payload)

        self.assertTrue(contract.requires_human)
        self.assertEqual(contract.message, "Vou consultar a proprietária.")

    def test_contract_from_message_analysis_supports_optional_fields(self) -> None:
        analysis = MessageAnalysis(
            intent="menu_opcao_1",
            original_message="quero 2 marmitex",
            intencao="fazer_pedido",
            produto="marmitex",
            quantidade=2,
            confianca=0.9,
            precisa_confirmacao=False,
        )

        contract = AgentResponseContract.from_message_agent_response(analysis)

        self.assertTrue(contract.success)
        self.assertEqual(contract.intent, "fazer_pedido")
        self.assertEqual(contract.message, "quero 2 marmitex")
        self.assertTrue(contract.order_updated)

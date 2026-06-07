from .base import ConversationFlowBaseTestCase
from .snapshots import build_conversation_snapshot, format_conversation_snapshot


class ConversationSnapshotsTests(ConversationFlowBaseTestCase):
    def test_build_snapshot_returns_same_number_of_steps(self) -> None:
        telefone = "5511999992501"
        self._enable_fake_complements()
        history = self._run_conversation(telefone, ["oi", "1", "1", "2", "não quero"])

        snapshot = build_conversation_snapshot(history)

        self.assertEqual(len(snapshot), len(history))

    def test_snapshot_contains_user_and_bot_messages(self) -> None:
        telefone = "5511999992502"
        history = self._run_conversation(telefone, ["oi"])

        snapshot = build_conversation_snapshot(history)

        self.assertEqual(snapshot[0]["user_message"], "oi")
        self.assertIn("Como posso ajudar", snapshot[0]["bot_response"])

    def test_snapshot_contains_before_and_after_awaiting_response(self) -> None:
        telefone = "5511999992503"
        self._enable_fake_complements()
        history = self._run_conversation(telefone, ["oi", "1"])

        snapshot = build_conversation_snapshot(history)

        self.assertEqual(snapshot[0]["before_awaiting_response"], "")
        self.assertEqual(snapshot[0]["after_awaiting_response"], "menu_principal")
        self.assertEqual(snapshot[1]["before_awaiting_response"], "menu_principal")

    def test_snapshot_contains_contract_information(self) -> None:
        telefone = "5511999992504"
        self._enable_fake_complements()
        history = self._run_conversation(telefone, ["oi", "1", "1", "2"])

        snapshot = build_conversation_snapshot(history)

        self.assertTrue(snapshot[3]["contract_success"])
        self.assertEqual(snapshot[3]["contract_intent"], "fazer_pedido")
        self.assertEqual(snapshot[3]["contract_next_state"], "aguardando_tipo_entrega")
        self.assertEqual(snapshot[3]["contract_awaiting_response"], "complemento")

    def test_snapshot_contains_state_machine_information_when_mapped(self) -> None:
        telefone = "5511999992505"
        self._enable_fake_complements()
        history = self._run_conversation(telefone, ["oi", "1", "1", "2"])

        snapshot = build_conversation_snapshot(history)

        self.assertEqual(snapshot[1]["state_machine_expected_next"], "produto")
        self.assertTrue(snapshot[1]["state_machine_allowed"])
        self.assertEqual(snapshot[3]["state_machine_expected_next"], "complemento")
        self.assertTrue(snapshot[3]["state_machine_allowed"])

    def test_format_snapshot_returns_readable_text(self) -> None:
        telefone = "5511999992506"
        self._enable_fake_complements()
        history = self._run_conversation(telefone, ["oi", "1", "1", "2", "não quero"])

        snapshot = build_conversation_snapshot(history)
        text = format_conversation_snapshot(snapshot)

        self.assertIn("Conversation snapshot:", text)
        self.assertIn("before=", text)
        self.assertIn("after=", text)
        self.assertIn("total=", text)
        self.assertIn("bot=", text)

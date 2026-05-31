from django.core.management.base import BaseCommand

import app.agents.orchestrator_agent as orchestrator_module
from app.agents.orchestrator_agent import OrchestratorAgent
from app.agents.conversation_state import AtendimentoStatus


class Command(BaseCommand):
    help = "Simula como o OrchestratorAgent reage as intencoes estruturadas."

    def handle(self, *args, **options):
        orchestrator = OrchestratorAgent()
        self._mock_state_side_effects(orchestrator)
        scenarios = [
            "qual o cardápio de hoje?",
            "tem feijoada hoje?",
            "quero falar com atendente",
            "cancela meu pedido",
            "vou retirar no local",
            "entrega na Rua Bahia 1000",
        ]

        self.stdout.write("mensagem | intencao | intent_resultado | final_response")
        self.stdout.write("-" * 160)

        for message in scenarios:
            analysis = orchestrator.message_agent.analyze(message)
            fake_state = self._build_fake_state_for_message(message)
            result = orchestrator._route_structured_intent(
                analysis=analysis,
                message=message,
                phone_key="SIMULACAO",
                conversation_state=fake_state,
                instructions=orchestrator.instructions_agent.get_instructions(),
                cardapio=orchestrator.cardapio_agent.get_cardapio(),
                rag_snippets=[],
                file_info=None,
                file_name="",
                file_mimetype="",
            )
            if result is None:
                self.stdout.write(f"{message} | {analysis.intencao} | sem_rota | sem_acao_nesta_etapa")
                continue
            final_response = (result.get("final_response") or "").replace("\n", " ").strip()
            self.stdout.write(
                f"{message} | {analysis.intencao} | {result.get('intent')} | {final_response}"
            )

    def _mock_state_side_effects(self, orchestrator: OrchestratorAgent) -> None:
        orchestrator_module.update_state = lambda *args, **kwargs: None
        orchestrator_module.reset_state = lambda *args, **kwargs: None
        orchestrator.order_agent.process_message = lambda *args, **kwargs: {
            "state": {"simulado": True},
            "response": "Fluxo de pedido atualizado (simulacao).",
        }

    def _build_fake_state_for_message(self, message: str):
        in_order_messages = {"vou retirar no local", "entrega na Rua Bahia 1000"}
        status = (
            AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA
            if message in in_order_messages
            else AtendimentoStatus.INICIO
        )
        return type(
            "FakeState",
            (),
            {
                "status_atendimento": status,
                "ultima_intencao": "fazer_pedido" if message in in_order_messages else "",
                "aguardando_resposta": "tipo_entrega" if message in in_order_messages else "",
                "itens_pedido": [{"produto": "marmitex individual", "quantidade": 1}] if message in in_order_messages else [],
                "produto": "marmitex_individual" if message in in_order_messages else "",
                "quantidade": 1 if message in in_order_messages else 0,
                "valor_total": 21.0 if message in in_order_messages else 0.0,
                "tipo_entrega": "",
                "endereco": "",
                "forma_pagamento": "",
            },
        )()

from django.core.management.base import BaseCommand

from app.agents.message_agent import MessageAgent


class Command(BaseCommand):
    help = "Simula a interpretacao estruturada de mensagens do WhatsApp."

    def handle(self, *args, **options):
        agent = MessageAgent()
        sample_state = {
            "status_atendimento": "aguardando_quantidade",
            "ultima_intencao": "fazer_pedido",
            "aguardando_resposta": "quantidade",
            "pedido_atual": {
                "produto": "marmitex_individual",
                "quantidade": 3,
                "tipo_entrega": None,
                "endereco": None,
                "forma_pagamento": None,
            },
        }
        messages = [
            "quero 3 marmitex",
            "quero 2 marmitas para entregar",
            "vou retirar no local",
            "vou buscar aí",
            "entrega na Rua Bahia 1000",
            "qual o cardápio de hoje?",
            "tem feijoada hoje?",
            "quero falar com atendente",
            "na verdade quero 2",
            "cancela meu pedido",
            "quanto fica uma marmita para 3 pessoas?",
            "manda uma para 4 pessoas",
        ]

        headers = [
            "mensagem",
            "intencao",
            "produto",
            "quantidade",
            "tipo_marmita",
            "tipo_entrega",
            "endereco",
            "confianca",
            "precisa_confirmacao",
        ]
        self.stdout.write(" | ".join(headers))
        self.stdout.write("-" * 160)

        for message in messages:
            state = sample_state if message == "na verdade quero 2" else None
            result = agent.analyze(message, state_summary=state)
            values = [
                message,
                result.intencao,
                result.produto or "",
                str(result.quantidade or ""),
                result.tipo_marmita or "",
                result.tipo_entrega or "",
                result.endereco or "",
                f"{result.confianca:.2f}",
                str(result.precisa_confirmacao).lower(),
            ]
            self.stdout.write(" | ".join(values))

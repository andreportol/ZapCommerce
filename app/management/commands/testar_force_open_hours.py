import os

from django.core.management.base import BaseCommand
from django.test.utils import override_settings

from app.agents.orchestrator_agent import OrchestratorAgent
from app.agents.conversation_state import AtendimentoStatus


class Command(BaseCommand):
    help = "Valida FORCE_OPEN_HOURS com cenarios DEBUG on/off sem depender do horario real."

    def handle(self, *args, **options):
        results = []
        scenarios = [
            {"name": "A", "debug": True, "force": "true", "expected_block": False},
            {"name": "B", "debug": True, "force": "false", "expected_block": True},
            {"name": "C", "debug": False, "force": "true", "expected_block": True},
        ]

        for scenario in scenarios:
            with override_settings(DEBUG=scenario["debug"]):
                if scenario["force"] is None:
                    os.environ.pop("FORCE_OPEN_HOURS", None)
                else:
                    os.environ["FORCE_OPEN_HOURS"] = scenario["force"]

                agent = OrchestratorAgent()
                # Simula fora do horario para teste deterministico.
                agent._is_within_business_hours_now = lambda: False
                fake_state = type(
                    "FakeState",
                    (),
                    {"status_atendimento": AtendimentoStatus.INICIO, "ultima_intencao": ""},
                )()
                blocked = agent._should_block_by_business_hours("quero 1 marmitex", fake_state)
                ok = blocked == scenario["expected_block"]
                results.append((scenario["name"], ok, blocked, scenario["expected_block"], scenario["debug"], scenario["force"]))

        self.stdout.write("cenario | DEBUG | FORCE_OPEN_HOURS | bloqueado? | esperado | status")
        self.stdout.write("-" * 100)
        for item in results:
            name, ok, blocked, expected, debug, force = item
            self.stdout.write(
                f"{name} | {debug} | {force} | {str(blocked).lower()} | {str(expected).lower()} | {'OK' if ok else 'ERRO'}"
            )


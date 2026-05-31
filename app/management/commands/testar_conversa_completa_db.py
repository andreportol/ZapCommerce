import unicodedata

from django.core.management.base import BaseCommand
from django.db import OperationalError, transaction

from app.agents.orchestrator_agent import OrchestratorAgent
from app.agents.conversation_state import AtendimentoStatus, get_or_create_state
from app.models import Cliente


class Command(BaseCommand):
    help = "Teste de regressao ponta a ponta com persistencia real em PostgreSQL (somente telefones fake de teste)."

    TEST_PHONES = [
        "5599999991001",
        "5599999991002",
        "5599999991003",
        "5599999991004",
        "5599999991005",
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--force-open-hours",
            action="store_true",
            help="Forca horario aberto apenas durante o comando para evitar bloqueio por hora atual.",
        )
        parser.add_argument(
            "--keep-test-data",
            action="store_true",
            help="Nao limpa dados fake ao final (debug).",
        )

    def handle(self, *args, **options):
        keep_test_data = bool(options.get("keep_test_data"))
        force_open_hours = bool(options.get("force_open_hours"))
        cleanup_ok = True

        orchestrator = OrchestratorAgent()
        if force_open_hours:
            orchestrator._is_open_for_orders = lambda: True
            orchestrator._should_block_by_business_hours = lambda *_args, **_kwargs: False

        scenarios = [
            {
                "name": "Cenario 1 - Marmita ambigua + entrega + individual",
                "phone": "5599999991001",
                "messages": ["oi", "quero 2 marmitas para entregar", "individual", "Rua Bahia 1000", "pix"],
                "validator": self._validate_scenario_1,
            },
            {
                "name": "Cenario 2 - Marmitex direto + retirada",
                "phone": "5599999991002",
                "messages": ["oi", "quero 3 marmitex", "vou buscar aí", "dinheiro"],
                "validator": self._validate_scenario_2,
            },
            {
                "name": "Cenario 3 - Marmita 4 pessoas + entrega",
                "phone": "5599999991003",
                "messages": ["manda uma para 4 pessoas", "entrega", "Rua Ceará 500", "cartao"],
                "validator": self._validate_scenario_3,
            },
            {
                "name": "Cenario 4 - Correcao de quantidade",
                "phone": "5599999991004",
                "messages": ["quero 3 marmitex", "na verdade quero 2", "retirada"],
                "validator": self._validate_scenario_4,
            },
            {
                "name": "Cenario 5 - Cliente nao sabe tipo",
                "phone": "5599999991005",
                "messages": ["quero 2 marmitas", "não sei", "para 3 pessoas"],
                "validator": self._validate_scenario_5,
            },
        ]

        self.stdout.write("tipo_teste=postgresql_real")
        self.stdout.write(f"force_open_hours={'sim' if force_open_hours else 'nao'}")
        self.stdout.write("=" * 220)

        passed = 0
        failed = 0
        failures: list[str] = []

        try:
            self._cleanup_test_data(self.TEST_PHONES)
        except OperationalError as exc:
            self.stdout.write(self.style.ERROR(f"ERRO de conexao com PostgreSQL: {exc}"))
            self.stdout.write("Dica: valide se o PostgreSQL esta ativo e se as credenciais do .env estao corretas.")
            return

        for scenario in scenarios:
            phone = scenario["phone"]
            transcript = []
            self.stdout.write(f"\n{scenario['name']}")
            self.stdout.write(f"telefone_fake={phone}")
            self.stdout.write("-" * 220)

            try:
                self._cleanup_test_data([phone])
            except OperationalError as exc:
                failed += 1
                failures.append(f"{scenario['name']}: falha ao limpar dados iniciais ({exc})")
                self.stdout.write(self.style.ERROR(f"status=ERRO"))
                self.stdout.write(f"observacoes=falha ao limpar dados iniciais: {exc}")
                continue

            scenario_error = None
            for idx, message in enumerate(scenario["messages"], start=1):
                try:
                    result = orchestrator.handle_message(message=message, telefone=phone)
                    state = get_or_create_state(phone)
                except OperationalError as exc:
                    scenario_error = f"erro de banco durante execucao: {exc}"
                    break
                response = (result.get("final_response") or "").replace("\n", " ").strip()
                snapshot = {
                    "status_atendimento": state.status_atendimento,
                    "aguardando_resposta": state.aguardando_resposta,
                    "produto": state.produto,
                    "quantidade": state.quantidade,
                    "tipo_entrega": state.tipo_entrega,
                    "endereco": state.endereco,
                    "forma_pagamento": state.forma_pagamento,
                }
                transcript.append({"message": message, "response": response, "state": snapshot})
                state_line = (
                    f"status={snapshot['status_atendimento']}, aguardando={snapshot['aguardando_resposta']}, "
                    f"produto={snapshot['produto']}, quantidade={snapshot['quantidade']}, "
                    f"tipo_entrega={snapshot['tipo_entrega']}, endereco={snapshot['endereco']}, pagamento={snapshot['forma_pagamento']}"
                )
                self.stdout.write(f"[{idx}] msg={message}")
                self.stdout.write(f"    bot={response}")
                self.stdout.write(f"    estado={state_line}")

            if scenario_error:
                failed += 1
                failures.append(f"{scenario['name']}: {scenario_error}")
                self.stdout.write("status=ERRO")
                self.stdout.write(f"observacoes={scenario_error}")
            else:
                ok, notes = scenario["validator"](transcript)
                if ok:
                    passed += 1
                else:
                    failed += 1
                    failures.append(f"{scenario['name']}: {notes}")
                self.stdout.write(f"status={'OK' if ok else 'ERRO'}")
                self.stdout.write(f"observacoes={notes}")

            if not keep_test_data:
                try:
                    self._cleanup_test_data([phone])
                except OperationalError:
                    cleanup_ok = False
            else:
                cleanup_ok = False

        if not keep_test_data:
            try:
                self._cleanup_test_data(self.TEST_PHONES)
            except OperationalError:
                cleanup_ok = False

        self.stdout.write("\n" + "=" * 220)
        self.stdout.write(f"total_cenarios={len(scenarios)}")
        self.stdout.write(f"cenarios_aprovados={passed}")
        self.stdout.write(f"cenarios_com_erro={failed}")
        self.stdout.write(f"dados_teste_limpos={'sim' if cleanup_ok and not keep_test_data else 'nao'}")
        self.stdout.write(
            "avisos_seguranca=limpeza restrita aos telefones fake "
            + ", ".join(self.TEST_PHONES)
        )
        if failures:
            self.stdout.write("principais_falhas:")
            for item in failures:
                self.stdout.write(f"- {item}")
        else:
            self.stdout.write("principais_falhas=nenhuma")

    def _cleanup_test_data(self, phones: list[str]) -> None:
        safe_phones = [p for p in phones if p in self.TEST_PHONES]
        if not safe_phones:
            return
        with transaction.atomic():
            Cliente.objects.filter(telefone__in=safe_phones).delete()

    def _normalize(self, text: str) -> str:
        raw = (text or "").strip().lower()
        raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
        return " ".join(raw.split())

    def _validate_scenario_1(self, transcript: list[dict]) -> tuple[bool, str]:
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        s4 = transcript[3]["state"]
        s5 = transcript[4]["state"]
        checks = {
            "passo2_marmita_ambigua": s2["produto"] == "marmita",
            "passo2_qtd_2": s2["quantidade"] == 2,
            "passo2_tipo_entrega_entrega": s2["tipo_entrega"] == "entrega",
            "passo3_produto_individual": s3["produto"] == "marmitex_individual",
            "passo3_qtd_2": s3["quantidade"] == 2,
            "passo4_endereco_salvo": bool(s4["endereco"]) and "bahia" in self._normalize(s4["endereco"]),
            "passo5_pagamento_pix": self._normalize(s5["forma_pagamento"]) == "pix",
            # Assercoes explicitas do ajuste solicitado:
            "passo5_status_aguardando_comprovante": s5["status_atendimento"] == AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            "passo5_aguardando_comprovante": s5["aguardando_resposta"] == "comprovante",
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            return (False, "falhas: " + ", ".join(failed))
        return (True, "OK: " + ", ".join(checks.keys()))

    def _validate_scenario_2(self, transcript: list[dict]) -> tuple[bool, str]:
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        s4 = transcript[3]["state"]
        checks = [
            s2["produto"] == "marmitex_individual",
            s2["quantidade"] == 3,
            s3["tipo_entrega"] == "retirada",
            self._normalize(s3["endereco"]) == "retirada no local",
            self._normalize(s4["forma_pagamento"]) == "dinheiro",
        ]
        return (all(checks), "fluxo esperado para retirada" if all(checks) else "falha em produto/quantidade/retirada/pagamento")

    def _validate_scenario_3(self, transcript: list[dict]) -> tuple[bool, str]:
        s1 = transcript[0]["state"]
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        s4 = transcript[3]["state"]
        checks = {
            "passo1_produto_marmita_4": s1["produto"] == "marmita_4_pessoas",
            "passo1_qtd_1": s1["quantidade"] == 1,
            "passo3_tipo_entrega_entrega": s3["tipo_entrega"] == "entrega",
            "passo3_endereco_ceara": "cear" in self._normalize(s3["endereco"]),
            "passo4_pagamento_cartao": self._normalize(s4["forma_pagamento"]) == "cartao",
            # Assercoes explicitas do ajuste solicitado para mensagem "entrega":
            "passo2_status_aguardando_endereco": s2["status_atendimento"] == AtendimentoStatus.AGUARDANDO_ENDERECO,
            "passo2_aguardando_endereco": s2["aguardando_resposta"] == "endereco",
            "passo2_tipo_entrega_entrega": s2["tipo_entrega"] == "entrega",
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            return (False, "falhas: " + ", ".join(failed))
        return (True, "OK: " + ", ".join(checks.keys()))

    def _validate_scenario_4(self, transcript: list[dict]) -> tuple[bool, str]:
        s1 = transcript[0]["state"]
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        checks = [
            s1["quantidade"] == 3,
            s2["quantidade"] == 2,
            s3["tipo_entrega"] == "retirada",
            self._normalize(s3["endereco"]) == "retirada no local",
        ]
        return (all(checks), "fluxo esperado para alteracao de quantidade" if all(checks) else "quantidade/retirada nao bateu")

    def _validate_scenario_5(self, transcript: list[dict]) -> tuple[bool, str]:
        s1 = transcript[0]["state"]
        s2 = transcript[1]["state"]
        s3 = transcript[2]["state"]
        r2 = self._normalize(transcript[1]["response"])
        checks = [
            s1["produto"] == "marmita",
            s1["quantidade"] == 2,
            s2["produto"] == "marmita" and s2["quantidade"] == 2,
            "nao consegui identificar o tipo" in r2,
            s3["produto"] == "marmita_3_pessoas",
            s3["quantidade"] == 2,
            s3["status_atendimento"] == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
        ]
        return (all(checks), "fluxo esperado para duvida de tipo" if all(checks) else "falha no tratamento de nao sei")

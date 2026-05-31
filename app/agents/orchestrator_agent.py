import re
import unicodedata

from django.utils import timezone

from .base_agent import AgentExecutionError, create_base_agent, run_text
from .cardapio_agent import CardapioAgent
from .database_agent import DatabaseAgent
from .file_agent import FileAgent
from .instructions_agent import InstructionsAgent
from .llm_config import LLMConfigError
from .message_agent import MessageAgent
from .order_agent import OrderAgent
from .rag import RagAgent
from .conversation_state import AtendimentoStatus, get_or_create_state, reset_state, update_state


class OrchestratorAgent:
    """Coordena agentes e gera resposta final com LLM."""

    def __init__(self) -> None:
        self.message_agent = MessageAgent()
        self.instructions_agent = InstructionsAgent()
        self.cardapio_agent = CardapioAgent()
        self.rag_agent = RagAgent()
        self.order_agent = OrderAgent()
        self.database_agent = DatabaseAgent()
        self.file_agent = FileAgent()
        self._llm_agent = None
        try:
            self._llm_agent = create_base_agent(
                name="OrchestratorAgent",
                instructions=(
                    "Voce e um assistente de atendimento para WhatsApp de uma marmitaria.\n"
                    "Responda em portugues do Brasil, de forma objetiva, educada e natural.\n"
                    "Soe como atendente humano: linguagem simples, cordial e direta.\n"
                    "Evite tom robotico, frases engessadas e texto longo.\n"
                    "Quando fizer sentido, use no maximo 1 emoji discreto.\n"
                    "Nao invente dados.\n"
                    "Se faltarem informacoes para localizar pedido, informe isso e solicite numero do pedido.\n"
                    "Nao confirme pagamento automaticamente.\n"
                    "Nao altere status de pedido.\n"
                    "Nao diga que gravou dados no banco."
                ),
            )
        except LLMConfigError:
            self._llm_agent = None

    def handle_message(
        self,
        message: str,
        file_name: str = "",
        file_mimetype: str = "",
        telefone: str = "",
    ) -> dict:
        phone_key = (telefone or "sessao_padrao").strip()
        conversation_state = get_or_create_state(phone_key)
        if conversation_state.status_atendimento == AtendimentoStatus.FORA_HORARIO and self._is_acknowledgement(message):
            reset_state(phone_key)
            return {
                "intent": "encerramento",
                "database": {"implemented": False, "message": "Cliente reconheceu aviso fora do horario.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": "Certo 😊 Quando estiver dentro do horario de pedidos, e so me chamar.",
            }

        if self._is_cancel_request(message):
            has_order_context = bool(conversation_state.itens_pedido or conversation_state.produto or conversation_state.valor_total)
            reset_state(phone_key)
            return {
                "intent": "cancelar",
                "database": {"implemented": False, "message": "Cancelamento local de estado.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": (
                    "Pedido cancelado. Se precisar de algo mais, e so me chamar."
                    if has_order_context
                    else "Nao ha pedido em andamento para cancelar. Se quiser, posso te ajudar com um novo pedido."
                ),
            }

        if self._should_block_by_business_hours(message, conversation_state):
            if conversation_state.status_atendimento != AtendimentoStatus.INICIO:
                reset_state(phone_key)
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.FORA_HORARIO,
                aguardando_resposta="fora_horario",
            )
            return {
                "intent": "fora_horario",
                "database": {"implemented": False, "message": "Atendimento fora do horario de pedidos.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": self._outside_business_hours_response(message),
            }

        if self._is_new_order_request(message):
            previous_status = conversation_state.status_atendimento
            if previous_status != AtendimentoStatus.INICIO:
                reset_state(phone_key)
            order_data = self.order_agent.process_message(phone_key, "quero fazer pedido")
            prefix = "Certo, vou iniciar um novo pedido.\n\n"
            if previous_status == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
                prefix = (
                    "Certo, vou iniciar um novo pedido.\n"
                    "O pedido anterior continua aguardando conferencia do comprovante pela equipe.\n\n"
                )
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Novo fluxo de pedido iniciado.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": self.rag_agent.search(message, top_k=2).get("results", []),
                "file_info": None,
                "order_state": order_data.get("state"),
                "final_response": f"{prefix}{self._start_order_prompt()}",
            }

        if (
            conversation_state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO
            and self._is_order_confirmation_from_offer(message)
        ):
            order_data = self.order_agent.process_message(phone_key, "quero fazer pedido")
            response = self._start_order_prompt()
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Fluxo de pedido em andamento.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": self.rag_agent.search(message, top_k=2).get("results", []),
                "file_info": None,
                "order_state": order_data.get("state"),
                "final_response": response,
            }

        analysis = self.message_agent.analyze(message)
        instructions = self.instructions_agent.get_instructions()
        cardapio = self.cardapio_agent.get_cardapio()
        rag_result = self.rag_agent.search(message, top_k=4)
        rag_snippets = rag_result.get("results", [])
        file_info = self.file_agent.parse_file_info(file_name, file_mimetype) if (file_name or file_mimetype) else None

        if (
            conversation_state.status_atendimento == AtendimentoStatus.CONSULTANDO_CARDAPIO
            and self._is_cardapio_followup(message)
        ):
            cardapio_response = self._build_cardapio_response(message, cardapio)
            return {
                "intent": "consultando_cardapio",
                "database": {"implemented": False, "message": "Consulta local de cardapio.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": cardapio_response,
            }

        if analysis.menu_option == "1" and conversation_state.status_atendimento == AtendimentoStatus.INICIO:
            order_data = self.order_agent.process_message(phone_key, "quero fazer pedido")
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Fluxo de pedido em andamento.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": order_data.get("state"),
                "final_response": self._start_order_prompt(),
            }

        if analysis.menu_option == "2" and conversation_state.status_atendimento == AtendimentoStatus.INICIO:
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.CONSULTANDO_CARDAPIO,
                aguardando_resposta="cardapio",
            )
            return {
                "intent": "consultando_cardapio",
                "database": {"implemented": False, "message": "Consulta local de cardapio.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": self._build_cardapio_response("hoje", cardapio, respect_business_hours=True),
            }

        if (
            conversation_state.status_atendimento == AtendimentoStatus.INICIO
            and self._is_explicit_start_order(message)
        ):
            order_data = self.order_agent.process_message(phone_key, "quero fazer pedido")
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Fluxo de pedido em andamento.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": order_data.get("state"),
                "final_response": self._start_order_prompt(),
            }

        if self._is_order_flow_message(message, conversation_state):
            if self._is_menu_request_during_order(message, conversation_state):
                cardapio_response = self._build_cardapio_response_for_order(message, cardapio, conversation_state)
                if conversation_state.status_atendimento in {
                    AtendimentoStatus.AGUARDANDO_PRODUTO,
                    AtendimentoStatus.FAZENDO_PEDIDO,
                    AtendimentoStatus.AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO,
                }:
                    update_state(phone_key, status_atendimento=AtendimentoStatus.AGUARDANDO_PRODUTO)
                return {
                    "intent": "consultando_cardapio",
                    "database": {"implemented": False, "message": "Fluxo de pedido em andamento.", "data": None},
                    "instructions": instructions,
                    "cardapio_loaded": bool(cardapio),
                    "rag_results": rag_snippets,
                    "file_info": file_info.__dict__ if file_info else None,
                    "order_state": get_or_create_state(phone_key).__dict__,
                    "final_response": cardapio_response,
                }

            if self._is_total_price_question(message) and conversation_state.valor_total > 0:
                total = f"R$ {conversation_state.valor_total:.2f}".replace(".", ",")
                return {
                    "intent": "fazer_pedido",
                    "database": {"implemented": False, "message": "Fluxo de pedido em andamento.", "data": None},
                    "instructions": instructions,
                    "cardapio_loaded": bool(cardapio),
                    "rag_results": rag_snippets,
                    "file_info": file_info.__dict__ if file_info else None,
                    "order_state": conversation_state.__dict__,
                    "final_response": f"O total do seu pedido e {total}.",
                }

            order_data = self.order_agent.process_message(
                phone_key,
                message,
                file_name=file_name,
                file_mimetype=file_mimetype,
            )
            final_response = order_data.get("response", "")
            if not self._is_open_for_orders() and self._is_price_question_context(message):
                final_response = self._adjust_price_response_outside_business_hours(final_response)
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Fluxo de pedido em andamento.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": order_data.get("state"),
                "final_response": final_response,
            }

        menu_response = self._handle_menu_option(analysis.menu_option)
        if menu_response:
            return {
                "intent": analysis.intent,
                "database": {"implemented": False, "message": "Fluxo de menu local.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": menu_response,
            }

        if analysis.intent == "consultar pedido":
            db_result = self.database_agent.get_order_status(message)
        elif analysis.intent == "consultar pagamento":
            db_result = self.database_agent.get_payment_status(message)
        else:
            db_result = self.database_agent.general_lookup(message)

        context = self._build_context(
            message=message,
            intent=analysis.intent,
            instructions=instructions,
            cardapio=cardapio,
            rag_snippets=rag_snippets,
            db_result=db_result,
            file_info=file_info,
        )
        rule_response = self._response_from_rag_rules(message=message, cardapio=cardapio, rag_snippets=rag_snippets)
        if rule_response:
            final_response = rule_response
            if self._is_price_question_context(message):
                update_state(phone_key, ultima_intencao="consultar_valores")
        else:
            final_response = self._generate_final_response(
                context=context,
                intent=analysis.intent,
                has_file=file_info is not None,
                rag_snippets=rag_snippets,
            )
        self._maybe_mark_awaiting_order_confirmation(phone_key, final_response)
        return {
            "intent": analysis.intent,
            "database": db_result,
            "instructions": instructions,
            "cardapio_loaded": bool(cardapio),
            "rag_results": rag_snippets,
            "file_info": file_info.__dict__ if file_info else None,
            "final_response": final_response,
        }

    def _is_price_question_context(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return any(term in text for term in ["valor", "valores", "preco", "precos", "quanto custa", "custa"])

    def _is_cancel_request(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return any(term in text for term in ["cancelar", "cancela", "quero cancelar", "cancelar pedido"])

    def _is_order_confirmation_from_offer(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        confirmations = {
            "sim",
            "quero",
            "eu quero",
            "gostaria",
            "quero sim",
            "pode ser",
            "beleza",
            "ok",
            "isso",
            "bora",
            "vamos",
            "pode fazer",
            "quero fazer pedido",
        }
        return text in confirmations

    def _is_explicit_start_order(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return text in {
            "quero fazer pedido",
            "eu quero fazer pedido",
            "quero fazer o pedido",
            "eu quero fazer o pedido",
            "eu quero fazer um pedido",
            "quero pedir",
            "gostaria de fazer pedido",
            "gostaria de fazer um pedido",
            "quero fazer encomenda",
            "quero fazer uma encomenda",
            "quero fazer um encomenda",
            "gostaria de fazer encomenda",
            "gostaria de fazer uma encomenda",
        }

    def _is_new_order_request(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return any(
            term in text
            for term in [
                "novo pedido",
                "fazer novo pedido",
                "fazer um novo pedido",
                "quero fazer novo pedido",
                "quero fazer um novo pedido",
                "outro pedido",
                "fazer outro pedido",
                "quero outro pedido",
            ]
        )

    def _normalize_short_text(self, text: str) -> str:
        raw = (text or "").strip().lower()
        raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
        raw = re.sub(r"[^a-z0-9\s]", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()

    def _start_order_prompt(self) -> str:
        return (
            "Perfeito 😊 Vamos fazer seu pedido.\n\n"
            "Voce deseja:\n"
            "1 - Marmitex individual\n"
            "2 - Marmita para 2 pessoas\n"
            "3 - Marmita para 3 pessoas\n"
            "4 - Marmita para 4 pessoas\n"
            "5 - Marmita para 5 pessoas\n\n"
            'Ou, se preferir, me diga direto a quantidade. Exemplo: "quero 3 marmitex".'
        )

    def _maybe_mark_awaiting_order_confirmation(self, telefone: str, response: str) -> None:
        text = (response or "").lower()
        offer_patterns = [
            "se quiser fazer um pedido",
            "se quiser fazer pedido",
            "quiser fazer um pedido",
            "quiser fazer pedido",
            "e so me avisar",
            "é só me avisar",
        ]
        if any(p in text for p in offer_patterns):
            state = get_or_create_state(telefone)
            if state.status_atendimento == AtendimentoStatus.INICIO:
                from .conversation_state import update_state

                update_state(
                    telefone,
                    status_atendimento=AtendimentoStatus.AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO,
                    aguardando_resposta="confirmacao_fazer_pedido",
                )

    def _is_order_flow_message(self, message: str, state) -> bool:
        text = (message or "").strip().lower()
        wants_order = any(
            k in text
            for k in [
                "fazer pedido",
                "quero fazer pedido",
                "quero pedir",
                "gostaria de pedir",
            "quero marmita",
            "quero marmitex",
            "encomenda",
            "encomendar",
            "quero encomenda",
            "fazer encomenda",
            "marmita",
            "marmitex",
            "pedido",
                "pedir",
            ]
        )
        affirmative = text in {"sim", "quero", "gostaria"}
        order_statuses = {
            AtendimentoStatus.FAZENDO_PEDIDO,
            AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM,
            AtendimentoStatus.AGUARDANDO_PRODUTO,
            AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA,
            AtendimentoStatus.AGUARDANDO_QUANTIDADE,
            AtendimentoStatus.AGUARDANDO_ENDERECO,
            AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO,
        }
        in_order = state.status_atendimento in order_statuses or state.ultima_intencao == "fazer_pedido"
        return wants_order or (affirmative and in_order) or in_order

    def _is_open_for_orders(self) -> bool:
        now = timezone.localtime()
        is_monday_to_saturday = 0 <= now.weekday() <= 5
        current_minutes = (now.hour * 60) + now.minute
        opens_at = (9 * 60)
        closes_at = (12 * 60) + 30
        return is_monday_to_saturday and opens_at <= current_minutes <= closes_at

    def _should_block_by_business_hours(self, message: str, state) -> bool:
        if self._is_open_for_orders():
            return False
        text = self._normalize_short_text(message)
        order_attempt = self._is_business_hours_order_attempt(text)
        if self._is_menu_request_during_order(message, state):
            return False
        if state.status_atendimento == AtendimentoStatus.CONSULTANDO_CARDAPIO and not order_attempt:
            return False
        if state.status_atendimento != AtendimentoStatus.INICIO or state.ultima_intencao == "fazer_pedido":
            return True
        return self._is_greeting(message) or order_attempt

    def _is_business_hours_order_attempt(self, normalized_text: str) -> bool:
        if normalized_text == "1":
            return True
        has_product = "marmitex" in normalized_text or "marmita" in normalized_text
        is_price_question = any(term in normalized_text for term in ["valor", "valores", "preco", "precos", "quanto custa", "custa"])
        is_menu_question = "cardapio" in normalized_text or "menu" in normalized_text
        if has_product and not is_price_question and not is_menu_question:
            return True
        terms = [
            "pedido",
            "pedir",
            "fazer pedido",
            "fazer o pedido",
            "quero fazer pedido",
            "quero fazer o pedido",
            "encomenda",
            "encomendar",
            "fazer encomenda",
            "fazer uma encomenda",
            "quero fazer encomenda",
            "quero fazer uma encomenda",
            "quero marmitex",
            "quero marmita",
            "vou querer",
            "reservar",
            "reserva",
        ]
        return any(term in normalized_text for term in terms)

    def _outside_business_hours_response(self, message: str) -> str:
        if self._is_greeting(message):
            return (
                "Olá! No momento estamos fora do horário de pedidos.\n\n"
                "Pedidos/encomendas: segunda a sábado, das 9h às 12h30.\n"
                "Entregas e retiradas: das 11h às 13h.\n\n"
                "Se quiser, posso te mostrar o cardápio. Para isso, digite 2."
            )
        return (
            "No momento estamos fora do horário de pedidos.\n\n"
            "Pedidos/encomendas: segunda a sábado, das 9h às 12h30.\n"
            "Entregas e retiradas: das 11h às 13h.\n"
            "Por favor, chame dentro desse horário para fazer sua encomenda."
        )

    def _adjust_price_response_outside_business_hours(self, response: str) -> str:
        text = (response or "").strip()
        if not text:
            return text
        remove_lines = [
            "Se quiser, posso continuar seu pedido 😊",
            "Quer continuar seu pedido? 😊",
        ]
        for line in remove_lines:
            text = text.replace(f"\n\n{line}", "").replace(line, "")
        text = text.strip()
        return (
            f"{text}\n\n"
            "Pedidos/encomendas podem ser feitos de segunda a sábado, das 9h às 12h30."
        )

    def _is_acknowledgement(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return text in {
            "ok",
            "okay",
            "certo",
            "ta bom",
            "tá bom",
            "esta bom",
            "está bom",
            "beleza",
            "blz",
            "obrigado",
            "obrigada",
            "valeu",
            "combinado",
            "entendi",
        }

    def _is_greeting(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return text in {
            "oi",
            "ola",
            "olá",
            "bom dia",
            "boa tarde",
            "boa noite",
            "oi bom dia",
            "oi boa tarde",
            "oi boa noite",
        }

    def _is_total_price_question(self, message: str) -> bool:
        text = (message or "").strip().lower()
        return "valor total" in text or ("total" in text and "pedido" in text)

    def _is_menu_request_during_order(self, message: str, state) -> bool:
        text = self._normalize_short_text(message)
        triggers = [
            "cardapio",
            "menu de hoje",
            "comida de hoje",
            "o que tem hoje",
            "primeiro preciso saber o cardapio",
            "me informe o cardapio",
            "qual o prato de hoje",
        ]
        if any(t in text for t in triggers):
            return True
        if state.status_atendimento == AtendimentoStatus.INICIO and state.ultima_intencao != "fazer_pedido":
            return False
        return bool(self._extract_weekday(text))

    def _is_cardapio_followup(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return (
            self._is_today_request(text)
            or self._is_weekly_cardapio_request(text)
            or bool(self._extract_weekday(text))
            or "cardapio" in text
            or "menu" in text
            or "prato" in text
        )

    def _is_today_request(self, normalized_text: str) -> bool:
        return normalized_text in {"hoje", "o de hoje", "de hoje", "cardapio de hoje", "menu de hoje"} or "hoje" in normalized_text

    def _build_cardapio_response(self, message: str, cardapio: str, respect_business_hours: bool = True) -> str:
        normalized = self._normalize_short_text(message)
        if self._is_weekly_cardapio_request(normalized):
            return self._build_weekly_cardapio_response(cardapio)

        day = self._extract_weekday(message or "")
        if respect_business_hours and not self._is_open_for_orders() and (not day or self._is_today_request(normalized)):
            return self._cardapio_after_hours_response()

        if not day or self._is_today_request(normalized):
            day = self._current_weekday_ptbr()
            prefix = f"Claro 😊 Hoje é {self._display_weekday(day)}. O cardápio de hoje é:"
        else:
            prefix = f"Claro 😊 O cardápio de {self._display_weekday(day)} é:"

        day_menu = self._extract_day_menu(cardapio, day)
        if not day_menu:
            return "Nao encontrei cardápio cadastrado para esse dia. Pode me dizer outro dia da semana?"
        return f"{prefix}\n\n{day_menu}"

    def _cardapio_after_hours_response(self) -> str:
        return (
            "O cardápio de hoje já encerrou junto com o horário de pedidos.\n\n"
            "Pedidos/encomendas podem ser feitos de segunda a sábado, das 9h às 12h30.\n"
            "Entregas e retiradas acontecem das 11h às 13h.\n\n"
            "Se quiser, posso te mostrar o cardápio da semana ou de um dia específico. "
            "Exemplo: cardápio de terça-feira."
        )

    def _is_weekly_cardapio_request(self, normalized_text: str) -> bool:
        compact = normalized_text.replace(" ", "")
        weekly_terms = [
            "cardapio semanal",
            "cardapio samanal",
            "cardapio da semana",
            "cardapio de semana",
            "cardapio de toda a semana",
            "cardapio toda semana",
            "cardapio semana toda",
            "cardapio da semana toda",
            "menu semanal",
            "menu da semana",
            "toda a semana",
            "semana toda",
            "todos os dias",
        ]
        compact_terms = [
            "cardapiosemanal",
            "cardapiosamanal",
            "cardapiodatodasemana",
            "cardapiodetodaasemana",
            "cardapiodasemana",
        ]
        return any(term in normalized_text for term in weekly_terms) or any(term in compact for term in compact_terms)

    def _build_weekly_cardapio_response(self, cardapio: str) -> str:
        days = ["segunda-feira", "terca-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sabado"]
        sections = []
        for day in days:
            day_menu = self._extract_day_menu(cardapio, day)
            if not day_menu:
                continue
            sections.append(f"*{self._display_weekday(day).capitalize()}*\n{day_menu}")

        if not sections:
            return "Nao encontrei o cardápio semanal cadastrado."

        return "Claro 😊 Esse é o cardápio da semana:\n\n" + "\n\n".join(sections)

    def _display_weekday(self, day: str) -> str:
        labels = {
            "segunda-feira": "segunda-feira",
            "terca-feira": "terça-feira",
            "quarta-feira": "quarta-feira",
            "quinta-feira": "quinta-feira",
            "sexta-feira": "sexta-feira",
            "sabado": "sábado",
            "domingo": "domingo",
        }
        return labels.get(day, day)

    def _build_cardapio_response_for_order(self, message: str, cardapio: str, state) -> str:
        normalized = self._normalize_short_text(message)
        if self._is_weekly_cardapio_request(normalized):
            return f"{self._build_weekly_cardapio_response(cardapio)}\n\n{self._order_continuation_prompt(state)}"

        day = self._extract_weekday(message or "")
        if not day:
            day = self._current_weekday_ptbr()
        day_menu = self._extract_day_menu(cardapio, day)
        continuation = self._order_continuation_prompt(state)
        if day_menu:
            return (
                f"Claro 😊 O cardápio de {self._display_weekday(day)} é:\n\n"
                f"{day_menu}\n\n"
                f"{continuation}"
            )
        return (
            "Posso te informar o cardápio, mas preciso confirmar o dia da semana primeiro.\n\n"
            f"{continuation}"
        )

    def _order_continuation_prompt(self, state) -> str:
        if not state.itens_pedido and not state.produto:
            return "Agora, para continuar seu pedido, voce deseja marmitex individual ou marmita para quantas pessoas?"
        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA:
            return "Agora, para continuar seu pedido, me diga para quantas pessoas e a marmita."
        if not state.tipo_entrega:
            return "Agora, para continuar seu pedido, voce prefere entrega ou retirada no local?"
        if state.tipo_entrega == "entrega" and not state.endereco:
            return "Agora, para continuar seu pedido, me informe o endereco de entrega, por favor."
        if not state.forma_pagamento:
            return "Agora, para continuar seu pedido, qual sera a forma de pagamento? Pix, dinheiro ou cartao?"
        if state.forma_pagamento == "Pix" and state.status_atendimento == AtendimentoStatus.AGUARDANDO_COMPROVANTE:
            return "Agora, para continuar seu pedido, pode enviar o comprovante por aqui."
        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
            return "Seu comprovante ja foi recebido e esta aguardando conferencia."
        return "Agora, para continuar seu pedido, confirme se esta tudo certo, por favor."

    def _handle_menu_option(self, menu_option: str) -> str:
        if menu_option == "1":
            return (
                "Perfeito! Para fazer seu pedido, me informe por favor:\n"
                "o tipo de marmita desejada e a quantidade de pessoas.\n"
                "Tambem me diga se e para entrega (com endereco) "
                "ou se voce vai retirar no local, e qual sera a forma de pagamento."
            )
        if menu_option == "2":
            return (
                "Claro! Me diga o dia da semana que voce quer consultar "
                "(por exemplo: segunda, terca, quarta...)."
            )
        if menu_option == "3":
            return (
                "Trabalhamos com marmitex individual e marmitas para 2, 3, 4 e 5 pessoas. "
                "Para pedidos acima de 5 pessoas, preciso consultar a proprietaria."
            )
        if menu_option == "4":
            return "Certo! Vou encaminhar seu atendimento para uma atendente. Aguarde um momento, por favor."
        return ""

    def _build_context(
        self,
        message: str,
        intent: str,
        instructions: str,
        cardapio: str,
        rag_snippets: list[dict],
        db_result: dict,
        file_info,
    ) -> str:
        file_section = "nenhum"
        if file_info is not None:
            file_section = (
                f"nome={file_info.nome or 'nao informado'}, "
                f"extensao={file_info.extensao or 'nao informada'}, "
                f"mimetype={file_info.mimetype or 'nao informado'}"
            )

        rag_section = "\n".join(
            f"- {item.get('text', '')}" for item in rag_snippets if item.get("text")
        ) or "Nenhum trecho relevante encontrado."

        return (
            f"Mensagem do usuario: {message}\n"
            f"Intencao detectada: {intent}\n"
            f"Resultado atual do banco: {db_result.get('message')}\n"
            f"Dados retornados do banco: {db_result.get('data')}\n"
            f"Arquivo recebido: {file_section}\n"
            f"Instrucoes de atendimento: {instructions}\n"
            f"Trechos recuperados pelo RAG:\n{rag_section}\n"
            f"Cardapio em arquivo texto:\n{cardapio or 'Nao ha cardapio carregado.'}\n"
            "Gere apenas a resposta final para o usuario em 1 a 4 frases curtas."
        )

    def _generate_final_response(self, context: str, intent: str, has_file: bool, rag_snippets: list[dict]) -> str:
        if not rag_snippets:
            return (
                "Nao encontrei dados suficientes nas instrucoes para responder com seguranca. "
                "Pode me dar mais detalhes, por favor?"
            )
        if self._llm_agent is not None:
            try:
                response = run_text(self._llm_agent, context)
                if response:
                    return response
            except (AgentExecutionError, ValueError):
                pass
        return self._fallback_response(intent, has_file)

    def _fallback_response(self, intent: str, has_file: bool) -> str:
        if has_file or intent == "envio de comprovante":
            return (
                "Recebi seu arquivo e ele sera analisado pela equipe. "
                "Por seguranca, nao confirmamos pagamento automaticamente por aqui."
            )
        if intent == "consultar pedido":
            return (
                "Para consultar o status do seu pedido, preciso de mais dados. "
                "Por favor, me informe o numero do pedido."
            )
        if intent == "consultar pagamento":
            return (
                "Posso te ajudar com pagamento, mas preciso do numero do pedido "
                "para localizar as informacoes corretas."
            )
        if intent == "atendimento humano":
            return "Entendi. Vou encaminhar seu atendimento para uma pessoa da equipe."
        return "Posso te ajudar melhor se voce me contar mais detalhes do que precisa."

    def _response_from_rag_rules(self, message: str, cardapio: str, rag_snippets: list[dict]) -> str:
        msg = message.lower()
        rag_text = " ".join(item.get("text", "") for item in rag_snippets).lower()

        if "marmitex" in msg and ("custa" in msg or "valor" in msg or "preco" in msg or "preço" in msg):
            if "r$ 21,00" in rag_text or "r$ 21,00" in cardapio.lower() or "r$ 21,00" in rag_text.replace(" ", ""):
                return "A marmitex individual custa R$ 21,00."

        people_count = self._extract_people_count(msg)
        if people_count is not None:
            if people_count > 5:
                if "acima de 5 pessoas" in rag_text or "mais de 5 pessoas" in rag_text:
                    return (
                        "Para pedidos acima de 5 pessoas, preciso consultar a proprietaria "
                        "do estabelecimento para confirmar o valor certinho."
                    )
            if 2 <= people_count <= 5:
                value = self._extract_price_for_people(rag_text, people_count)
                if value:
                    return f"A marmita para {people_count} pessoas custa {value}."

        normalized_msg = self._normalize_short_text(message)
        if "cardapio" in normalized_msg:
            if self._is_weekly_cardapio_request(normalized_msg):
                return self._build_weekly_cardapio_response(cardapio)

            day = self._extract_weekday(normalized_msg)
            if not day:
                day = self._current_weekday_ptbr()
            day_menu = self._extract_day_menu(cardapio, day)
            if day_menu:
                return f"Considerando {day}, o cardapio e:\n{day_menu}"
            return "Para eu te informar certinho, pode confirmar qual dia da semana voce quer consultar?"

        return ""

    def _extract_people_count(self, text: str) -> int | None:
        m = re.search(r"\b(\d{1,2})\s*pessoas?\b", text)
        if not m:
            return None
        return int(m.group(1))

    def _extract_price_for_people(self, rag_text: str, people_count: int) -> str:
        pattern = rf"marmita para {people_count} pessoas?:\s*(r\$\s*\d+,\d{{2}})"
        m = re.search(pattern, rag_text, flags=re.IGNORECASE)
        if not m:
            return ""
        return m.group(1).upper().replace("  ", " ")

    def _extract_weekday(self, text: str) -> str:
        normalized = self._normalize_short_text(text)
        aliases = {
            "segunda-feira": ["segunda feira", "segunda-feira", "segunda"],
            "terca-feira": ["terca feira", "terca-feira", "terca", "terça feira", "terça-feira", "terça"],
            "quarta-feira": ["quarta feira", "quarta-feira", "quarta"],
            "quinta-feira": ["quinta feira", "quinta-feira", "quinta"],
            "sexta-feira": ["sexta feira", "sexta-feira", "sexta"],
            "sabado": ["sabado", "sabado feira", "sábado", "sábado feira"],
            "domingo": ["domingo"],
        }
        for canonical, values in aliases.items():
            if any(value in normalized for value in values):
                return canonical
        return ""

    def _current_weekday_ptbr(self) -> str:
        mapping = {
            0: "segunda-feira",
            1: "terca-feira",
            2: "quarta-feira",
            3: "quinta-feira",
            4: "sexta-feira",
            5: "sabado",
            6: "domingo",
        }
        return mapping.get(timezone.localdate().weekday(), "")

    def _extract_day_menu(self, cardapio: str, day: str) -> str:
        if not cardapio or not day:
            return ""
        aliases = {
            "segunda-feira": ["segunda-feira", "segunda feira", "segunda"],
            "terca-feira": ["terca-feira", "terça-feira", "terca feira", "terça feira", "terca", "terça"],
            "quarta-feira": ["quarta-feira"],
            "quinta-feira": ["quinta-feira"],
            "sexta-feira": ["sexta-feira"],
            "sabado": ["sabado", "sábado", "sabado-feira", "sábado-feira"],
            "domingo": ["domingo"],
        }
        candidates = aliases.get(day, [day])
        for candidate in candidates:
            escaped_day = re.escape(candidate).replace(r"\ ", r"\s+")
            pattern = rf"##\s*{escaped_day}\s*(.*?)(?=\n##\s|\Z)"
            m = re.search(pattern, cardapio, flags=re.IGNORECASE | re.DOTALL)
            if not m:
                continue
            lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
            return "\n".join(lines[:4]).strip()
        return ""


def run_orchestrator_test_cases() -> dict:
    orchestrator = OrchestratorAgent()
    status_case = orchestrator.handle_message("Olá, quero saber o status do meu pedido")
    file_case = orchestrator.handle_message(
        "Segue o comprovante de pagamento",
        file_name="comprovante_pix.jpg",
        file_mimetype="image/jpeg",
    )
    return {
        "status_case": status_case,
        "file_case": file_case,
    }

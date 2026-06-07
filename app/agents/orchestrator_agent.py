import re
import unicodedata
import logging
import os

from django.conf import settings
from django.test.testcases import DatabaseOperationForbidden
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
from .conversation_state import AtendimentoStatus, ConversationState, get_or_create_state, reset_state, update_state
from app.business_config import (
    DAY_ORDER,
    delivery_hours_summary,
    format_day_display,
    format_time_br,
    get_active_business_settings,
    is_open_for_orders,
    order_hours_for_day,
    order_hours_summary,
    owner_consultation_message,
    pickup_hours_summary,
)
from app.order_catalog import format_brl, get_order_product, get_order_product_by_people, get_order_product_choices, list_order_products

logger = logging.getLogger(__name__)

BEBIDAS_DISPONIVEIS: list[str] = []


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
        self._force_open_hours_log_once = False
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
        try:
            conversation_state = self._safe_get_state(phone_key, message)
            if self._is_recovery_command(message):
                return self._handle_recovery_command(phone_key, message, conversation_state)

            invalid_reason = self._invalid_state_reason(conversation_state)
            if invalid_reason:
                logger.warning(
                    "Estado de conversa invalido detectado telefone=%s mensagem=%r estado=%s motivo=%s acao=reset",
                    phone_key,
                    message,
                    self._state_snapshot(conversation_state),
                    invalid_reason,
                )
                self._safe_reset_state(phone_key, action="reset_invalid_state", message=message, state=conversation_state)
                return self._build_recovery_menu_result(
                    phone_key=phone_key,
                    note="Desculpe, tive uma dificuldade para continuar seu atendimento 😕\nVamos recomeçar.",
                    database_message="Estado invalido recuperado.",
                )

            if self._is_greeting(message) and self._has_pending_order_step(conversation_state):
                return self._build_pending_order_resume_result(phone_key, conversation_state)

            result = self._handle_message_impl(
                message=message,
                file_name=file_name,
                file_mimetype=file_mimetype,
                telefone=telefone,
            )
            final_response = (result.get("final_response") or "").strip()
            if final_response:
                return result

            logger.warning(
                "Resposta vazia detectada telefone=%s mensagem=%r estado=%s acao=reset",
                phone_key,
                message,
                self._state_snapshot(conversation_state),
            )
            self._safe_reset_state(phone_key, action="reset_empty_response", message=message, state=conversation_state)
            return self._build_recovery_menu_result(
                phone_key=phone_key,
                note="Desculpe, tive uma dificuldade para continuar seu atendimento 😕\nVamos recomeçar.",
                database_message="Resposta vazia recuperada.",
            )
        except Exception:
            logger.exception(
                "Erro interno no orquestrador telefone=%s mensagem=%r estado=%s acao=fallback",
                phone_key,
                message,
                self._state_snapshot_from_phone(phone_key),
            )
            self._safe_reset_state(phone_key, action="reset_exception_fallback", message=message)
            return self._build_recovery_menu_result(
                phone_key=phone_key,
                note="Desculpe, tive uma dificuldade para continuar seu atendimento 😕\nVamos recomeçar.",
                database_message="Fallback seguro por excecao.",
            )

    def _handle_message_impl(
        self,
        message: str,
        file_name: str = "",
        file_mimetype: str = "",
        telefone: str = "",
    ) -> dict:
        phone_key = (telefone or "sessao_padrao").strip()
        conversation_state = get_or_create_state(phone_key)
        if self._is_acknowledgement(message) and not self._has_active_order_context(conversation_state):
            reset_state(phone_key)
            return {
                "intent": "encerramento",
                "database": {"implemented": False, "message": "Cliente encerrou o atendimento atual.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": self._build_acknowledgement_response(conversation_state),
            }

        if self._should_block_by_business_hours(message, conversation_state):
            final_response = self._outside_business_hours_response(message, conversation_state)
            if conversation_state.status_atendimento != AtendimentoStatus.INICIO:
                reset_state(phone_key)
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.FORA_HORARIO,
                aguardando_resposta="fora_horario",
                ultima_intencao="fora_horario_informado",
            )
            return {
                "intent": "fora_horario",
                "database": {"implemented": False, "message": "Atendimento fora do horario de pedidos.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": final_response,
            }

        future_reservation_days = self._extract_future_contact_and_requested_days(message)
        if (
            future_reservation_days[0]
            and future_reservation_days[1]
            and not self._has_active_order_context(conversation_state)
        ):
            contact_day, requested_day = future_reservation_days
            return {
                "intent": "agendamento_contato_reserva",
                "database": {"implemented": False, "message": "Cliente informou que vai chamar em outro dia para reservar.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": self._build_future_contact_reservation_response(
                    message=message,
                    contact_day=contact_day,
                    requested_day=requested_day,
                ),
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
                    "Pedido cancelado. Se precisar de algo mais, é só me chamar."
                    if has_order_context
                    else "Não há pedido em andamento para cancelar. Se quiser, posso te ajudar com um novo pedido."
                ),
            }

        if conversation_state.aguardando_resposta == "entrega_bairro_ou_endereco":
            delivery_area_route = self._handle_delivery_area_followup(message=message, phone_key=phone_key)
            if delivery_area_route is not None:
                return delivery_area_route

        delivery_info_intent = self._detect_delivery_info_intent(message, conversation_state)
        if delivery_info_intent:
            if delivery_info_intent == "entrega_geral":
                update_state(
                    phone_key,
                    aguardando_resposta="entrega_bairro_ou_endereco",
                    ultima_intencao="duvida_entrega",
                )
            else:
                update_state(
                    phone_key,
                    aguardando_resposta="",
                    ultima_intencao="",
                )
            return {
                "intent": "duvida_entrega_retirada",
                "database": {"implemented": False, "message": "Resposta informativa sobre entrega/retirada.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": self._build_delivery_info_response(delivery_info_intent),
            }

        operational_info_route = self._route_operational_info_request(
            message=message,
            phone_key=phone_key,
            conversation_state=conversation_state,
        )
        if operational_info_route is not None:
            return operational_info_route

        if self._is_new_order_request(message):
            previous_status = conversation_state.status_atendimento
            if previous_status != AtendimentoStatus.INICIO:
                reset_state(phone_key)
            order_data = self._process_order_message(phone_key, "quero fazer pedido")
            prefix = "Certo 😊 Vou iniciar um novo pedido.\n\n"
            if previous_status == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
                prefix = (
                    "Certo 😊 Vou iniciar um novo pedido.\n"
                    "O pedido anterior continua aguardando conferência do comprovante pela equipe.\n\n"
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
            order_data = self._process_order_message(phone_key, "quero fazer pedido")
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

        if conversation_state.aguardando_resposta == "dia_cardapio":
            cardapio_day_route = self._handle_cardapio_day_selection_context(
                message=message,
                phone_key=phone_key,
                file_name=file_name,
                file_mimetype=file_mimetype,
            )
            if cardapio_day_route is not None:
                return cardapio_day_route

        cardapio_order_followup = self._handle_cardapio_quantity_order_followup(
            message=message,
            phone_key=phone_key,
            conversation_state=conversation_state,
            file_name=file_name,
            file_mimetype=file_mimetype,
        )
        if cardapio_order_followup is not None:
            return cardapio_order_followup

        analysis = self.message_agent.analyze(
            message,
            state_summary=self._build_intent_state_summary(conversation_state),
        )
        instructions = self.instructions_agent.get_instructions()
        cardapio = self.cardapio_agent.get_cardapio()
        rag_result = self.rag_agent.search(message, top_k=4)
        rag_snippets = rag_result.get("results", [])
        file_info = self.file_agent.parse_file_info(file_name, file_mimetype) if (file_name or file_mimetype) else None

        logger.info(
            "Message analysis message=%r legacy_intent=%s new_intent=%s confidence=%.2f needs_confirmation=%s "
            "produto=%r quantidade=%r tipo_entrega=%r endereco=%r",
            message,
            analysis.intent,
            analysis.intencao,
            analysis.confianca,
            analysis.precisa_confirmacao,
            analysis.produto,
            analysis.quantidade,
            analysis.tipo_entrega,
            analysis.endereco,
        )

        main_menu_option = self._extract_main_menu_option(message, conversation_state)
        if (
            analysis.intencao == "saudacao"
            and not main_menu_option
            and not self._has_active_order_context(conversation_state)
        ):
            return self._build_main_menu_result(
                phone_key=phone_key,
                instructions=instructions,
                cardapio=cardapio,
                rag_snippets=rag_snippets,
                file_info=file_info,
            )

        parallel_order_info_route = self._route_parallel_order_info_request(
            message=message,
            phone_key=phone_key,
            conversation_state=conversation_state,
            instructions=instructions,
            cardapio=cardapio,
            rag_snippets=rag_snippets,
            file_info=file_info,
        )
        if parallel_order_info_route is not None:
            return parallel_order_info_route

        if main_menu_option:
            main_menu_route = self._route_main_menu_option(
                menu_option=main_menu_option,
                phone_key=phone_key,
                instructions=instructions,
                cardapio=cardapio,
                rag_snippets=rag_snippets,
                file_info=file_info,
            )
            if main_menu_route is not None:
                return main_menu_route

        if (
            analysis.intencao != "desconhecida"
            and analysis.confianca >= 0.55
            and not analysis.precisa_confirmacao
        ):
            simple_route = self._route_structured_intent(
                analysis=analysis,
                message=message,
                phone_key=phone_key,
                conversation_state=conversation_state,
                instructions=instructions,
                cardapio=cardapio,
                rag_snippets=rag_snippets,
                file_info=file_info,
                file_name=file_name,
                file_mimetype=file_mimetype,
            )
            if simple_route is not None:
                return simple_route

        if self._is_price_question_context(message) or self._is_price_followup_context(message, conversation_state):
            final_response = self._build_price_response(message)
            if not self._is_open_for_orders():
                final_response = self._adjust_price_response_outside_business_hours(final_response)
                update_state(
                    phone_key,
                    status_atendimento=AtendimentoStatus.FORA_HORARIO,
                    ultima_intencao="consultar_valores",
                    aguardando_resposta="fora_horario",
                )
            else:
                update_state(phone_key, ultima_intencao="consultar_valores")
            return {
                "intent": "consultar_valores",
                "database": {"implemented": False, "message": "Consulta local de valores.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": final_response,
            }

        if (
            conversation_state.status_atendimento in {
                AtendimentoStatus.INICIO,
                AtendimentoStatus.FORA_HORARIO,
                AtendimentoStatus.CONSULTANDO_CARDAPIO,
            }
            and (analysis.menu_option == "2" or self._is_cardapio_followup(message))
        ):
            cardapio_message = "hoje" if analysis.menu_option == "2" else message
            cardapio_response_data = self._build_cardapio_response_data(
                cardapio_message,
                cardapio,
                respect_business_hours=False,
            )
            self._update_cardapio_state_from_response(
                phone_key=phone_key,
                response_data=cardapio_response_data,
            )
            return {
                "intent": "consultando_cardapio",
                "database": {"implemented": False, "message": "Consulta local de cardapio.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": cardapio_response_data["response"],
            }

        if (
            conversation_state.status_atendimento == AtendimentoStatus.CONSULTANDO_CARDAPIO
            and self._is_cardapio_followup(message)
        ):
            cardapio_response_data = self._build_cardapio_response_data(
                message,
                cardapio,
                respect_business_hours=False,
            )
            self._update_cardapio_state_from_response(
                phone_key=phone_key,
                response_data=cardapio_response_data,
            )
            return {
                "intent": "consultando_cardapio",
                "database": {"implemented": False, "message": "Consulta local de cardapio.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": cardapio_response_data["response"],
            }

        if analysis.menu_option == "1" and conversation_state.status_atendimento == AtendimentoStatus.INICIO:
            order_data = self._process_order_message(phone_key, "quero fazer pedido")
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
            cardapio_response_data = self._build_cardapio_response_data(
                "hoje",
                cardapio,
                respect_business_hours=True,
            )
            self._update_cardapio_state_from_response(
                phone_key=phone_key,
                response_data=cardapio_response_data,
            )
            return {
                "intent": "consultando_cardapio",
                "database": {"implemented": False, "message": "Consulta local de cardapio.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": cardapio_response_data["response"],
            }

        if (
            conversation_state.status_atendimento == AtendimentoStatus.INICIO
            and self._is_explicit_start_order(message)
        ):
            order_data = self._process_order_message(phone_key, "quero fazer pedido")
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

        if (
            conversation_state.status_atendimento == AtendimentoStatus.INICIO
            and self._looks_like_additional_request_without_order(message)
        ):
            order_data = self._process_order_message(phone_key, "quero fazer pedido")
            start_prompt = self._start_order_prompt()
            prompt_body = start_prompt.split("\n\n", 1)[1] if "\n\n" in start_prompt else start_prompt
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Fluxo de pedido iniciado a partir de pedido de observacao/adicional.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": order_data.get("state"),
                "final_response": (
                    "Claro 😊 Posso registrar essa observação no seu pedido.\n\n"
                    f"{prompt_body}"
                ),
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

            order_data = self._process_order_message(
                phone_key,
                message,
                structured_analysis=analysis.structured,
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
        if analysis.intencao == "desconhecida" and not self._has_active_order_context(conversation_state):
            return self._build_main_menu_result(
                phone_key=phone_key,
                instructions=instructions,
                cardapio=cardapio,
                rag_snippets=rag_snippets,
                file_info=file_info,
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

    def _route_structured_intent(
        self,
        analysis,
        message: str,
        phone_key: str,
        conversation_state,
        instructions: str,
        cardapio: str,
        rag_snippets: list[dict],
        file_info,
        file_name: str,
        file_mimetype: str,
    ) -> dict | None:
        if getattr(analysis, "menu_option", "") and self._has_pending_order_step(conversation_state):
            return None

        if analysis.intencao == "consultar_cardapio":
            cardapio_message = "hoje" if getattr(analysis, "menu_option", "") == "2" else (analysis.mensagem_livre or message)
            cardapio_response_data = self._build_cardapio_response_data(
                cardapio_message,
                cardapio,
                respect_business_hours=False,
            )
            self._update_cardapio_state_from_response(
                phone_key=phone_key,
                response_data=cardapio_response_data,
            )
            return {
                "intent": "consultando_cardapio",
                "database": {"implemented": False, "message": "Consulta local de cardapio via intencao estruturada.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": cardapio_response_data["response"],
            }

        if analysis.intencao == "consultar_preco":
            final_response = self._build_price_response(message)
            if not self._is_open_for_orders():
                final_response = self._adjust_price_response_outside_business_hours(final_response)
                update_state(
                    phone_key,
                    status_atendimento=AtendimentoStatus.FORA_HORARIO,
                    ultima_intencao="consultar_valores",
                    aguardando_resposta="fora_horario",
                )
            else:
                update_state(phone_key, ultima_intencao="consultar_valores")
            return {
                "intent": "consultar_valores",
                "database": {"implemented": False, "message": "Consulta local de valores via intencao estruturada.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": final_response,
            }

        if analysis.intencao == "falar_atendente":
            return {
                "intent": "atendimento_humano",
                "database": {"implemented": False, "message": "Encaminhamento para humano via intencao estruturada.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": "Certo! Vou encaminhar seu atendimento para uma atendente. Aguarde um momento, por favor.",
            }

        if analysis.intencao == "cancelar_pedido":
            has_order_context = bool(
                conversation_state.itens_pedido
                or conversation_state.produto
                or conversation_state.valor_total
            )
            reset_state(phone_key)
            return {
                "intent": "cancelar",
                "database": {"implemented": False, "message": "Cancelamento local de estado via intencao estruturada.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": (
                    "Pedido cancelado. Se precisar de algo mais, é só me chamar."
                    if has_order_context
                    else "Não há pedido em andamento para cancelar. Se quiser, posso te ajudar com um novo pedido."
                ),
            }

        if analysis.intencao in {"informar_retirada", "informar_endereco"}:
            if not self._is_order_flow_message(message, conversation_state):
                return None
            forwarded_message = message
            if analysis.intencao == "informar_retirada":
                forwarded_message = "retirada"
            elif analysis.intencao == "informar_endereco" and analysis.endereco:
                forwarded_message = f"entrega na {analysis.endereco}"
            order_data = self._process_order_message(
                phone_key,
                forwarded_message,
                structured_analysis=analysis.structured,
                file_name=file_name,
                file_mimetype=file_mimetype,
            )
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Fluxo de pedido em andamento via intencao estruturada.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": order_data.get("state"),
                "final_response": order_data.get("response", ""),
            }

        return None

    def _extract_main_menu_option(self, message: str, state) -> str:
        if self._has_pending_order_step(state):
            return ""
        if getattr(state, "aguardando_resposta", "") in {"dia_cardapio", "entrega_bairro_ou_endereco"}:
            return ""
        normalized = self._normalize_short_text(message)
        return normalized if normalized in {"1", "2", "3", "4"} else ""

    def _build_main_menu_result(
        self,
        phone_key: str,
        instructions: str,
        cardapio: str,
        rag_snippets: list[dict],
        file_info,
    ) -> dict:
        update_state(
            phone_key,
            status_atendimento=AtendimentoStatus.INICIO,
            aguardando_resposta="menu_principal",
            ultima_intencao="menu_principal",
        )
        return {
            "intent": "menu_principal",
            "database": {"implemented": False, "message": "Fluxo local do menu principal.", "data": None},
            "instructions": instructions,
            "cardapio_loaded": bool(cardapio),
            "rag_results": rag_snippets,
            "file_info": file_info.__dict__ if file_info else None,
            "final_response": self._main_menu_response(),
        }

    def _process_order_message(self, telefone: str, message: str, **kwargs) -> dict:
        order_data = self.order_agent.process_message(telefone, message, **kwargs)
        self.order_agent.persist_order_snapshot(telefone)
        return order_data

    def _handle_cardapio_quantity_order_followup(
        self,
        message: str,
        phone_key: str,
        conversation_state,
        file_name: str = "",
        file_mimetype: str = "",
    ) -> dict | None:
        if self._has_active_order_context(conversation_state):
            return None
        last_day = self._extract_last_consulted_day_from_state(conversation_state)
        if not last_day:
            return None

        quantity = self._extract_cardapio_followup_quantity(message)
        if quantity is None:
            return None

        forwarded_message = f"quero {quantity} marmitex"
        order_data = self._process_order_message(
            phone_key,
            forwarded_message,
            file_name=file_name,
            file_mimetype=file_mimetype,
        )
        final_response = (order_data.get("response") or "").strip()
        current_day = self._current_weekday_ptbr()
        if last_day and last_day != current_day:
            final_response = (
                f"{final_response}\n\n"
                f"Você tinha consultado o cardápio de {self._display_weekday(last_day)}. "
                f"Se esse pedido for para {self._display_weekday(last_day)}, me avise para eu manter esse dia certinho."
            )
        return {
            "intent": "fazer_pedido",
            "database": {"implemented": False, "message": "Fluxo de pedido iniciado a partir do último cardápio consultado.", "data": None},
            "instructions": self.instructions_agent.get_instructions(),
            "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
            "rag_results": self.rag_agent.search(message, top_k=2).get("results", []),
            "file_info": self.file_agent.parse_file_info(file_name, file_mimetype).__dict__ if (file_name or file_mimetype) else None,
            "order_state": order_data.get("state"),
            "final_response": final_response,
        }

    def _extract_cardapio_followup_quantity(self, message: str) -> int | None:
        text = self._normalize_short_text(message)
        if not text:
            return None
        if any(term in text for term in ["cardapio", "menu", "horario", "endereco", "entrega", "retirada"]):
            return None
        if any(term in text for term in ["marmitex", "marmita", "pedido"]):
            return None
        if not any(term in text for term in ["quero", "eu quero", "vou querer", "pode ser"]):
            return None
        return self.order_agent._to_int(text)

    def _build_recovery_menu_result(
        self,
        phone_key: str,
        note: str = "",
        database_message: str = "Fluxo de recuperacao do atendimento.",
    ) -> dict:
        try:
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.INICIO,
                aguardando_resposta="menu_principal",
                ultima_intencao="menu_principal",
            )
        except Exception:
            logger.exception(
                "Falha ao persistir estado de recuperacao telefone=%s acao=menu_recuperacao",
                phone_key,
            )
        lines = []
        if note:
            lines.append(note.strip())
            lines.append("")
        lines.extend(
            [
                "Como posso ajudar?",
                "",
                "1 - Fazer pedido",
                "2 - Saber o cardápio",
                "3 - Mais informações",
                "4 - Falar com a atendente",
            ]
        )
        return {
            "intent": "recuperacao_atendimento",
            "database": {"implemented": False, "message": database_message, "data": None},
            "instructions": self.instructions_agent.get_instructions(),
            "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
            "rag_results": [],
            "file_info": None,
            "final_response": "\n".join(lines).strip(),
        }

    def _safe_get_state(self, phone_key: str, message: str) -> ConversationState:
        try:
            return get_or_create_state(phone_key)
        except Exception:
            logger.exception(
                "Falha ao carregar estado telefone=%s mensagem=%r acao=reset_tentativa",
                phone_key,
                message,
            )
            try:
                return reset_state(phone_key)
            except Exception:
                logger.exception(
                    "Falha ao recriar estado telefone=%s mensagem=%r acao=estado_padrao_memoria",
                    phone_key,
                    message,
                )
                return ConversationState(telefone=phone_key)

    def _safe_reset_state(self, phone_key: str, action: str, message: str, state=None) -> None:
        try:
            reset_state(phone_key)
            logger.warning(
                "Estado resetado telefone=%s mensagem=%r estado=%s acao=%s",
                phone_key,
                message,
                self._state_snapshot(state),
                action,
            )
        except Exception:
            logger.exception(
                "Falha ao resetar estado telefone=%s mensagem=%r estado=%s acao=%s",
                phone_key,
                message,
                self._state_snapshot(state),
                action,
            )

    def _state_snapshot(self, state) -> dict:
        if state is None:
            return {}
        return {
            "status_atendimento": getattr(state, "status_atendimento", ""),
            "ultima_intencao": getattr(state, "ultima_intencao", ""),
            "aguardando_resposta": getattr(state, "aguardando_resposta", ""),
            "produto": getattr(state, "produto", ""),
            "quantidade": getattr(state, "quantidade", 0),
            "tipo_entrega": getattr(state, "tipo_entrega", ""),
            "endereco": getattr(state, "endereco", ""),
            "forma_pagamento": getattr(state, "forma_pagamento", ""),
            "valor_total": getattr(state, "valor_total", 0.0),
            "itens_pedido": len(getattr(state, "itens_pedido", []) or []),
            "itens_pendentes": len(getattr(state, "itens_pendentes", []) or []),
        }

    def _state_snapshot_from_phone(self, phone_key: str) -> dict:
        try:
            return self._state_snapshot(get_or_create_state(phone_key))
        except Exception:
            return {"telefone": phone_key, "estado": "indisponivel"}

    def _is_recovery_command(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return text in {
            "menu",
            "reiniciar",
            "recomecar",
            "recomecar atendimento",
            "comecar de novo",
            "novo atendimento",
        }

    def _handle_recovery_command(self, phone_key: str, message: str, state) -> dict:
        text = self._normalize_short_text(message)
        if text == "menu" and self._has_active_order_context(state):
            if getattr(state, "status_atendimento", "") == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
                self._safe_reset_state(
                    phone_key,
                    action="reset_menu_after_payment_conference",
                    message=message,
                    state=state,
                )
                return self._build_recovery_menu_result(
                    phone_key=phone_key,
                    note=(
                        "Certo 😊 Vou abrir um novo atendimento.\n"
                        "O pedido anterior continua aguardando conferência do comprovante pela equipe."
                    ),
                    database_message="Menu aberto apos conferencia pendente.",
                )
            return {
                "intent": "confirmar_abandono_pedido",
                "database": {"implemented": False, "message": "Pedido em andamento preservado durante pedido de menu.", "data": None},
                "instructions": self.instructions_agent.get_instructions(),
                "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
                "rag_results": [],
                "file_info": None,
                "final_response": (
                    "Seu pedido ainda está em andamento.\n\n"
                    "Se quiser abandonar este fluxo e voltar ao menu, digite reiniciar.\n"
                    "Se preferir começar outro pedido mantendo o anterior, digite novo pedido."
                ),
            }

        self._safe_reset_state(phone_key, action=f"reset_recovery_command:{text}", message=message, state=state)
        note = "Certo 😊 Vamos recomeçar seu atendimento."
        if getattr(state, "status_atendimento", "") == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
            note = (
                "Certo 😊 Vou iniciar um novo atendimento.\n"
                "O pedido anterior continua aguardando conferência do comprovante pela equipe."
            )
        return self._build_recovery_menu_result(
            phone_key=phone_key,
            note=note,
            database_message="Fluxo reiniciado por comando do usuario.",
        )

    def _build_pending_order_resume_result(self, phone_key: str, state) -> dict:
        if getattr(state, "status_atendimento", "") == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
            response = (
                "Seu comprovante já foi recebido e está aguardando conferência pela equipe.\n\n"
                "Se quiser iniciar um novo pedido, digite novo pedido. "
                "Se preferir voltar ao menu, digite menu."
            )
        else:
            response = (
                "Seu atendimento anterior ainda está em andamento.\n\n"
                f"{self._order_continuation_prompt(state)}"
            )
        return {
            "intent": "retomar_atendimento",
            "database": {"implemented": False, "message": "Fluxo retomado por saudacao durante etapa pendente.", "data": None},
            "instructions": self.instructions_agent.get_instructions(),
            "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
            "rag_results": [],
            "file_info": None,
            "final_response": response,
        }

    def _invalid_state_reason(self, state) -> str:
        if state is None:
            return "estado_ausente"

        if not isinstance(getattr(state, "itens_pedido", []), list):
            return "itens_pedido_invalido"
        if not isinstance(getattr(state, "itens_pendentes", []), list):
            return "itens_pendentes_invalido"
        if any(not isinstance(item, dict) for item in (getattr(state, "itens_pedido", []) or [])):
            return "itens_pedido_malformado"
        if any(not isinstance(item, dict) for item in (getattr(state, "itens_pendentes", []) or [])):
            return "itens_pendentes_malformado"

        known_statuses = {
            AtendimentoStatus.INICIO,
            AtendimentoStatus.FORA_HORARIO,
            AtendimentoStatus.CONSULTANDO_CARDAPIO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO,
            AtendimentoStatus.FAZENDO_PEDIDO,
            AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM,
            AtendimentoStatus.AGUARDANDO_PRODUTO,
            AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA,
            AtendimentoStatus.AGUARDANDO_QUANTIDADE,
            AtendimentoStatus.AGUARDANDO_ENDERECO,
            AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
            AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO,
            AtendimentoStatus.ENCAMINHAR_ATENDENTE,
        }
        known_waiting = {
            "",
            "menu_principal",
            "dia_cardapio",
            "entrega_bairro_ou_endereco",
            "fora_horario",
            "produto",
            "tipo_marmita",
            "quantidade",
            "complemento",
            "quantidade_complemento",
            "mais_complementos",
            "tipo_entrega",
            "endereco",
            "nome_cliente",
            "forma_pagamento",
            "confirmacao",
            "confirmacao_item",
            "comprovante",
            "conferencia_pagamento",
            "pessoas_marmita",
            "confirmacao_fazer_pedido",
            "consulta_proprietaria",
        }
        status = getattr(state, "status_atendimento", "")
        waiting = getattr(state, "aguardando_resposta", "")
        if status not in known_statuses:
            return f"status_desconhecido:{status}"
        if waiting not in known_waiting:
            return f"aguardando_resposta_desconhecida:{waiting}"

        has_order_payload = bool(
            getattr(state, "itens_pedido", [])
            or getattr(state, "itens_pendentes", [])
            or getattr(state, "produto", "")
            or getattr(state, "quantidade", 0)
            or getattr(state, "valor_total", 0.0)
        )
        tipo_entrega = getattr(state, "tipo_entrega", "")
        forma_pagamento = getattr(state, "forma_pagamento", "")

        if status == AtendimentoStatus.INICIO and has_order_payload:
            return "inicio_com_dados_de_pedido"
        if status == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA and not has_order_payload:
            return "aguardando_entrega_sem_pedido"
        if status == AtendimentoStatus.AGUARDANDO_ENDERECO and (not has_order_payload or tipo_entrega != "entrega"):
            return "aguardando_endereco_inconsistente"
        if status == AtendimentoStatus.AGUARDANDO_NOME_CLIENTE and (
            not has_order_payload or tipo_entrega not in {"entrega", "retirada"}
        ):
            return "aguardando_nome_sem_fluxo_valido"
        if status == AtendimentoStatus.AGUARDANDO_PAGAMENTO and (
            not has_order_payload or tipo_entrega not in {"entrega", "retirada"}
        ):
            return "aguardando_pagamento_sem_fluxo_valido"
        if status == AtendimentoStatus.AGUARDANDO_COMPROVANTE and (
            not has_order_payload or forma_pagamento != "Pix"
        ):
            return "aguardando_comprovante_sem_pix"
        if status == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO and (
            not has_order_payload or forma_pagamento != "Pix"
        ):
            return "aguardando_conferencia_sem_pix"
        if status == AtendimentoStatus.AGUARDANDO_CONFIRMACAO and not has_order_payload:
            return "aguardando_confirmacao_sem_pedido"
        return ""

    def _route_main_menu_option(
        self,
        menu_option: str,
        phone_key: str,
        instructions: str,
        cardapio: str,
        rag_snippets: list[dict],
        file_info,
    ) -> dict | None:
        if menu_option == "1":
            order_data = self._process_order_message(phone_key, "quero fazer pedido")
            return {
                "intent": "fazer_pedido",
                "database": {"implemented": False, "message": "Fluxo de pedido iniciado pelo menu principal.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": order_data.get("state"),
                "final_response": self._start_order_prompt(),
            }

        if menu_option == "2":
            cardapio_response_data = self._build_cardapio_response_data(
                "hoje",
                cardapio,
                respect_business_hours=True,
            )
            self._update_cardapio_state_from_response(
                phone_key=phone_key,
                response_data=cardapio_response_data,
            )
            return {
                "intent": "consultando_cardapio",
                "database": {"implemented": False, "message": "Consulta local de cardapio pelo menu principal.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "final_response": cardapio_response_data["response"],
            }

        menu_response = self._handle_menu_option(menu_option)
        if not menu_response:
            return None

        if menu_option == "3":
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.INICIO,
                aguardando_resposta="menu_principal",
                ultima_intencao="menu_principal",
            )
        elif menu_option == "4":
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.ENCAMINHAR_ATENDENTE,
                aguardando_resposta="",
                ultima_intencao="falar_atendente",
            )

        return {
            "intent": f"menu_opcao_{menu_option}",
            "database": {"implemented": False, "message": "Fluxo local do menu principal.", "data": None},
            "instructions": instructions,
            "cardapio_loaded": bool(cardapio),
            "rag_results": rag_snippets,
            "file_info": file_info.__dict__ if file_info else None,
            "final_response": menu_response,
        }

    def _is_price_question_context(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return any(term in text for term in ["valor", "valores", "preco", "precos", "quanto custa", "custa"])

    def _is_cancel_request(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return any(term in text for term in ["cancelar", "cancela", "quero cancelar", "cancelar pedido"])

    def _route_operational_info_request(self, message: str, phone_key: str, conversation_state) -> dict | None:
        if self._has_pending_order_step(conversation_state):
            return None

        info_intent = self._detect_operational_info_intent(message)
        if not info_intent:
            return None

        if info_intent == "horario_funcionamento":
            final_response = self._build_business_hours_response(message)
            ultima_intencao = "consultar_horario"
        elif info_intent == "localizacao":
            final_response = self._build_location_response()
            ultima_intencao = "consultar_localizacao"
        else:
            final_response = self._build_general_info_response()
            ultima_intencao = "consultar_informacoes"

        update_state(
            phone_key,
            status_atendimento=AtendimentoStatus.INICIO,
            aguardando_resposta="",
            ultima_intencao=ultima_intencao,
        )
        return {
            "intent": info_intent,
            "database": {"implemented": False, "message": "Resposta informativa local.", "data": None},
            "instructions": self.instructions_agent.get_instructions(),
            "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
            "rag_results": [],
            "file_info": None,
            "final_response": final_response,
        }

    def _route_parallel_order_info_request(
        self,
        message: str,
        phone_key: str,
        conversation_state,
        instructions: str,
        cardapio: str,
        rag_snippets: list[dict],
        file_info,
    ) -> dict | None:
        if not self._has_active_order_context(conversation_state):
            return None

        if self._is_beverage_info_request(message) and getattr(conversation_state, "aguardando_resposta", "") not in {
            "complemento",
            "quantidade_complemento",
            "mais_complementos",
        }:
            return {
                "intent": "consultar_bebidas",
                "database": {"implemented": False, "message": "Consulta de bebidas durante pedido em andamento.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": conversation_state.__dict__,
                "final_response": self._build_beverage_response_for_order(conversation_state),
            }

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
                "database": {"implemented": False, "message": "Consulta local de cardápio durante pedido em andamento.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": get_or_create_state(phone_key).__dict__,
                "final_response": cardapio_response,
            }

        info_intent = self._detect_operational_info_intent(message)
        if info_intent:
            if info_intent == "horario_funcionamento":
                final_response = self._build_parallel_order_followup_response(
                    self._build_business_hours_response(message),
                    conversation_state,
                )
            elif info_intent == "localizacao":
                final_response = self._build_parallel_order_followup_response(
                    self._build_location_response(),
                    conversation_state,
                )
            else:
                final_response = self._build_parallel_order_followup_response(
                    self._build_general_info_response(),
                    conversation_state,
                )
            return {
                "intent": info_intent,
                "database": {"implemented": False, "message": "Resposta informativa paralela durante pedido em andamento.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": conversation_state.__dict__,
                "final_response": final_response,
            }

        if self._is_payment_info_request(message):
            final_response = self._build_parallel_order_followup_response(
                "Aceitamos Pix, dinheiro e cartão 😊",
                conversation_state,
            )
            return {
                "intent": "consultar_pagamento",
                "database": {"implemented": False, "message": "Resposta sobre pagamento durante pedido em andamento.", "data": None},
                "instructions": instructions,
                "cardapio_loaded": bool(cardapio),
                "rag_results": rag_snippets,
                "file_info": file_info.__dict__ if file_info else None,
                "order_state": conversation_state.__dict__,
                "final_response": final_response,
            }

        return None

    def _detect_operational_info_intent(self, message: str) -> str:
        text = self._normalize_short_text(message)
        if not text:
            return ""

        hours_markers = [
            "horario de funcionamento",
            "que horas abre",
            "que horas fecha",
            "qual horario",
            "qual o horario",
            "atende ate que horas",
            "hoje funciona",
            "esta aberto",
            "esta aberta",
            "ta aberto",
            "ta aberta",
            "abre hoje",
            "fecha hoje",
            "funciona hoje",
        ]
        if any(term in text for term in hours_markers):
            return "horario_funcionamento"

        location_markers = [
            "onde fica",
            "qual o endereco",
            "qual endereco",
            "endereco",
            "localizacao",
            "onde voces ficam",
            "onde voces estao",
        ]
        if any(term in text for term in location_markers):
            return "localizacao"

        general_info_markers = [
            "quais as opcoes",
            "quais opcoes",
            "quais marmitas tem",
            "quais tamanhos",
            "mais informacoes",
            "mais informacao",
            "informacoes",
            "informacao",
            "opcoes de marmita",
            "tamanhos",
        ]
        if any(term in text for term in general_info_markers):
            return "informacoes_gerais"

        return ""

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

    def _looks_like_additional_request_without_order(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        if not text:
            return False
        if any(term in text for term in ["marmita", "marmitex", "pedido", "pedir"]):
            return False
        if any(term in text for term in ["cardapio", "menu", "valor", "preco", "entrega", "retirada", "retirar", "atendente"]):
            return False
        markers = [
            "acrescent",
            "adicion",
            "colocar mais",
            "extra",
            "adicional",
            "mais 1",
            "mais carne",
            "sem ",
            "retirar",
            "tirar",
            "trocar",
        ]
        return any(marker in text for marker in markers)

    def _start_order_prompt(self) -> str:
        choices = get_order_product_choices()
        if not choices:
            return (
                "No momento não há produtos de pedido disponíveis no catálogo. "
                "Se quiser, posso te encaminhar para a atendente."
            )

        lines = ["Perfeito 😊 Vamos fazer seu pedido.", "", "Você deseja:"]
        for item in choices:
            lines.append(f"{item['choice']} - {item['nome']}")
        lines.append("")
        lines.append('Ou, se preferir, me diga direto a quantidade. Exemplo: "quero 3 marmitex".')
        return "\n".join(lines)

    def _main_menu_response(self) -> str:
        return (
            "Olá! Seja bem-vindo(a). 😊\n"
            "Como posso ajudar?\n\n"
            "1 - Fazer pedido\n"
            "2 - Saber o cardápio\n"
            "3 - Mais informações\n"
            "4 - Falar com a atendente\n\n"
            "Digite o número da opção desejada."
        )

    def _build_business_hours_response(self, message: str) -> str:
        business = get_active_business_settings()
        text = self._normalize_short_text(message)
        lines = []

        if any(term in text for term in ["esta aberto", "esta aberta", "ta aberto", "ta aberta", "hoje funciona", "funciona hoje"]):
            if self._is_open_for_orders():
                lines.append("Sim, estamos dentro do horário de pedidos 😊")
            else:
                lines.append("No momento estamos fora do horário de pedidos.")
            lines.append("")

        lines.append("Funcionamos nos seguintes horários:")
        lines.append("")
        lines.append("Pedidos/encomendas:")
        lines.extend(self._build_schedule_lines(business, "pedido"))
        lines.append("")
        lines.append("Entregas e retiradas:")
        lines.extend(self._build_delivery_pickup_lines(business))
        return "\n".join(lines).strip()

    def _build_schedule_lines(self, business, window_kind: str) -> list[str]:
        field_names = {
            "pedido": ("abre_pedidos", "fecha_pedidos"),
            "entrega": ("abre_entregas", "fecha_entregas"),
            "retirada": ("abre_retiradas", "fecha_retiradas"),
        }
        start_field, end_field = field_names[window_kind]
        lines: list[str] = []
        for day_key in DAY_ORDER:
            schedule = business.schedule_for_day(day_key)
            day_label = format_day_display(day_key).capitalize()
            if not schedule or schedule.fechado:
                lines.append(f"* {day_label}: fechado")
                continue

            start_value = getattr(schedule, start_field)
            end_value = getattr(schedule, end_field)
            if start_value and end_value:
                lines.append(f"* {day_label}: {format_time_br(start_value)} às {format_time_br(end_value)}")
            else:
                lines.append(f"* {day_label}: indisponível")
        return lines

    def _build_delivery_pickup_lines(self, business) -> list[str]:
        lines: list[str] = []
        for day_key in DAY_ORDER:
            schedule = business.schedule_for_day(day_key)
            day_label = format_day_display(day_key).capitalize()
            if not schedule or schedule.fechado:
                lines.append(f"* {day_label}: sem atendimento")
                continue

            delivery_text = "entrega desativada"
            pickup_text = "retirada desativada"

            if business.aceita_entrega and schedule.abre_entregas and schedule.fecha_entregas:
                delivery_text = f"entrega {format_time_br(schedule.abre_entregas)} às {format_time_br(schedule.fecha_entregas)}"
            if business.aceita_retirada_local and schedule.abre_retiradas and schedule.fecha_retiradas:
                pickup_text = f"retirada {format_time_br(schedule.abre_retiradas)} às {format_time_br(schedule.fecha_retiradas)}"

            if delivery_text == pickup_text:
                lines.append(f"* {day_label}: {delivery_text}")
            else:
                lines.append(f"* {day_label}: {delivery_text}; {pickup_text}")
        return lines

    def _build_location_response(self) -> str:
        business = get_active_business_settings()
        endereco = (business.endereco_retirada or "").strip()
        if endereco:
            return (
                f"A retirada no local acontece em: {endereco}.\n\n"
                "Se quiser, também posso te informar os horários de atendimento ou entrega."
            )
        return (
            "O endereço da Marmitaria da Adriana ainda não foi configurado no sistema.\n\n"
            "Se quiser, posso te informar os horários de atendimento ou te encaminhar para a atendente."
        )

    def _build_general_info_response(self) -> str:
        available_products = list_order_products(only_available=True)
        if not available_products:
            return "No momento não há opções de pedido disponíveis no catálogo."

        return (
            f"{self._product_options_message()}\n\n"
            "Se quiser, também posso te informar o cardápio do dia, horários, entrega ou retirada."
        )

    def _product_options_message(self) -> str:
        available_products = list_order_products(only_available=True)
        if not available_products:
            return "No momento não há opções de pedido disponíveis no catálogo."

        lines = ["Trabalhamos com as seguintes opções 😊", ""]
        for index, product in enumerate(available_products, start=1):
            lines.append(f"{index} - {product['nome']}")
        lines.extend(["", owner_consultation_message()])
        return "\n".join(lines)

    def _list_available_beverages(self) -> list[str]:
        try:
            from app.models import Produto

            return list(
                Produto.objects.filter(
                    categoria=Produto.Categoria.BEBIDA,
                    disponivel=True,
                )
                .order_by("nome")
                .values_list("nome", flat=True)
            )
        except DatabaseOperationForbidden:
            return list(BEBIDAS_DISPONIVEIS)
        except Exception:
            return list(BEBIDAS_DISPONIVEIS)

    def _is_beverage_info_request(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        if not text:
            return False
        markers = [
            "bebida",
            "bebidas",
            "beber",
            "refrigerante",
            "refrigerantes",
            "coca",
            "guarana",
            "guaraná",
            "suco",
            "agua",
            "água",
        ]
        return any(marker in text for marker in markers)

    def _build_beverage_response_for_order(self, state) -> str:
        bebidas = self._list_available_beverages()
        continuation = self._pending_order_step_prompt(state)
        if bebidas:
            lines = ["Temos bebidas sim 😊", "", "No momento, estas são as opções disponíveis:"]
            for index, bebida in enumerate(bebidas, start=1):
                lines.append(f"{index} - {bebida}")
            lines.extend(["", "Deseja adicionar alguma bebida ao seu pedido?"])
            if continuation:
                lines.extend(["", "Ou, se preferir, podemos continuar:", "", continuation])
            return "\n".join(lines)

        lines = [
            "No momento as bebidas ainda não estão cadastradas no sistema 😊",
            "",
            "Posso continuar seu pedido normalmente.",
        ]
        if continuation:
            lines.extend(["", continuation])
        return "\n".join(lines)

    def _build_parallel_order_followup_response(self, info_response: str, state) -> str:
        continuation = self._pending_order_step_prompt(state)
        if not continuation:
            return info_response
        return f"{info_response}\n\nPara continuar seu pedido:\n\n{continuation}"

    def _pending_order_step_prompt(self, state) -> str:
        status = getattr(state, "status_atendimento", "")
        waiting = getattr(state, "aguardando_resposta", "")
        if waiting == "complemento":
            return self.order_agent._complement_prompt()
        if waiting == "quantidade_complemento":
            pending_option = self.order_agent._find_pending_complement(state)
            if pending_option is not None:
                return self.order_agent._prompt_complement_quantity(pending_option)
            return self.order_agent._complement_prompt()
        if waiting == "mais_complementos":
            return self.order_agent._more_complements_prompt()
        if status == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA:
            return self.order_agent._delivery_mode_prompt()
        if status == AtendimentoStatus.AGUARDANDO_ENDERECO:
            return self.order_agent._delivery_address_prompt()
        if status == AtendimentoStatus.AGUARDANDO_NOME_CLIENTE:
            return self.order_agent._customer_name_prompt()
        if status == AtendimentoStatus.AGUARDANDO_PAGAMENTO:
            return self.order_agent._payment_options_prompt()
        if status == AtendimentoStatus.AGUARDANDO_COMPROVANTE:
            return "Pode enviar o comprovante por aqui quando quiser."
        if status == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
            return "Seu comprovante já foi recebido e está aguardando conferência."
        if status == AtendimentoStatus.AGUARDANDO_CONFIRMACAO:
            return self.order_agent._build_order_summary(state)
        if status == AtendimentoStatus.AGUARDANDO_QUANTIDADE:
            return "Qual a quantidade desejada?"
        if status == AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA:
            return "Essa marmita é para quantas pessoas?"
        if status in {
            AtendimentoStatus.FAZENDO_PEDIDO,
            AtendimentoStatus.AGUARDANDO_PRODUTO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO,
        }:
            return self._start_order_prompt()
        return self._order_continuation_prompt(state)

    def _is_payment_info_request(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        if not text:
            return False
        return any(
            term in text
            for term in [
                "forma de pagamento",
                "formas de pagamento",
                "como paga",
                "como pagar",
                "aceita pix",
                "aceita cartao",
                "aceita cartão",
                "aceita dinheiro",
                "pagamento",
                "pix",
                "cartao",
                "cartão",
            ]
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
            "manda",
            "mandar",
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
            AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
            AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO,
        }
        in_order = state.status_atendimento in order_statuses or state.ultima_intencao == "fazer_pedido"
        return wants_order or (affirmative and in_order) or in_order

    def _has_pending_order_step(self, state) -> bool:
        if state is None:
            return False
        pending_statuses = {
            AtendimentoStatus.FAZENDO_PEDIDO,
            AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM,
            AtendimentoStatus.AGUARDANDO_PRODUTO,
            AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA,
            AtendimentoStatus.AGUARDANDO_QUANTIDADE,
            AtendimentoStatus.AGUARDANDO_ENDERECO,
            AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
            AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO,
        }
        return (
            getattr(state, "status_atendimento", "") in pending_statuses
            or getattr(state, "aguardando_resposta", "") in {
                "tipo_marmita",
                "quantidade",
                "complemento",
                "quantidade_complemento",
                "mais_complementos",
                "tipo_entrega",
                "endereco",
                "nome_cliente",
                "forma_pagamento",
                "confirmacao",
                "confirmacao_item",
                "comprovante",
                "conferencia_pagamento",
                "pessoas_marmita",
            }
            or getattr(state, "ultima_intencao", "") == "fazer_pedido"
        )

    def _is_open_for_orders(self) -> bool:
        if self._is_force_open_hours_enabled():
            return True
        return self._is_within_business_hours_now()

    def _has_active_order_context(self, state) -> bool:
        if state is None:
            return False
        order_statuses = {
            AtendimentoStatus.FAZENDO_PEDIDO,
            AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM,
            AtendimentoStatus.AGUARDANDO_PRODUTO,
            AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA,
            AtendimentoStatus.AGUARDANDO_QUANTIDADE,
            AtendimentoStatus.AGUARDANDO_ENDERECO,
            AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
            AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_FAZER_PEDIDO,
        }
        return (
            getattr(state, "status_atendimento", "") in order_statuses
            or getattr(state, "ultima_intencao", "") == "fazer_pedido"
        )

    def _is_within_business_hours_now(self) -> bool:
        return is_open_for_orders()

    def _is_force_open_hours_enabled(self) -> bool:
        force_open = (os.getenv("FORCE_OPEN_HOURS", "").strip().lower() == "true")
        if not force_open:
            return False
        if not settings.DEBUG:
            return False
        if not self._force_open_hours_log_once:
            logger.info(
                "FORCE_OPEN_HOURS ativo em ambiente DEBUG: ignorando bloqueio de horario para testes."
            )
            self._force_open_hours_log_once = True
        return True

    def _should_block_by_business_hours(self, message: str, state) -> bool:
        return not self._is_open_for_orders()

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

    def _detect_delivery_info_intent(self, message: str, state=None) -> str:
        text = self._normalize_short_text(message)
        if not text:
            return ""
        order_statuses = {
            AtendimentoStatus.FAZENDO_PEDIDO,
            AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM,
            AtendimentoStatus.AGUARDANDO_PRODUTO,
            AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA,
            AtendimentoStatus.AGUARDANDO_QUANTIDADE,
            AtendimentoStatus.AGUARDANDO_ENDERECO,
            AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
            AtendimentoStatus.AGUARDANDO_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
            AtendimentoStatus.AGUARDANDO_CONFIRMACAO,
        }
        if state is not None and (
            getattr(state, "status_atendimento", "") in order_statuses
            or getattr(state, "ultima_intencao", "") == "fazer_pedido"
        ):
            return ""

        has_delivery = any(
            term in text
            for term in [
                "entrega",
                "entregam",
                "entregar",
                "delivery",
                "horario de entrega",
                "horario entrega",
            ]
        )
        has_pickup = any(
            term in text
            for term in [
                "retirada",
                "retirar",
                "retira",
                "retiro",
                "buscar no local",
                "pegar no local",
                "horario de retirada",
                "horario retirada",
            ]
        )

        if not has_delivery and not has_pickup:
            return ""

        info_markers = any(
            term in text
            for term in [
                "?",
                "vcs",
                "voce",
                "vocês",
                "faz entrega",
                "fazem entrega",
                "quero saber",
                "tem delivery",
                "qual horario",
                "posso retirar",
                "entregam",
            ]
        )
        has_explicit_order_qty = bool(re.search(r"\b\d+\b", text))
        explicit_order_terms = any(
            term in text
            for term in ["quero pedir", "fazer pedido", "quero  ", "vou pedir", "pedido de"]
        )
        if self._is_business_hours_order_attempt(text) and not (info_markers and not has_explicit_order_qty and not explicit_order_terms):
            return ""

        if has_pickup and not has_delivery:
            return "retirada"
        if "marmitex" in text:
            return "entrega_marmitex"
        if "horario de entrega" in text or "horario entrega" in text:
            return "horario_entrega"
        return "entrega_geral"

    def _build_delivery_info_response(self, intent: str) -> str:
        business = get_active_business_settings()
        order_hours = order_hours_summary(business)
        delivery_hours = delivery_hours_summary(business)
        pickup_hours = pickup_hours_summary(business)

        if intent == "retirada":
            if not business.aceita_retirada_local:
                return "No momento a retirada no local não está disponível."
            return (
                "Sim, você também pode retirar no local 😊\n\n"
                f"As retiradas acontecem em {pickup_hours}.\n\n"
                f"Os pedidos/encomendas são feitos em {order_hours}."
            )
        if intent == "entrega_marmitex":
            if not business.aceita_entrega:
                return "No momento a entrega não está disponível. Se quiser, posso te orientar sobre retirada no local."
            return (
                "Sim, fazemos entrega de marmitex 😊\n\n"
                f"As entregas acontecem em {delivery_hours}.\n\n"
                f"Os pedidos/encomendas são feitos em {order_hours}."
            )
        if intent == "horario_entrega":
            if not business.aceita_entrega:
                return "No momento a entrega não está disponível."
            return f"As entregas acontecem em {delivery_hours}."
        if not business.aceita_entrega:
            return "No momento trabalhamos apenas com retirada no local."
        return (
            "Fazemos entrega, sim 😊\n\n"
            f"As entregas acontecem em {delivery_hours}.\n\n"
            "Para confirmar se conseguimos entregar no seu endereço, me envie o endereço ou o bairro."
        )

    def _handle_delivery_area_followup(self, message: str, phone_key: str) -> dict | None:
        location_type, location_label = self._extract_delivery_location_details(message)
        if not location_type:
            return None

        update_state(
            phone_key,
            aguardando_resposta="",
            ultima_intencao="duvida_entrega",
        )
        if location_type == "bairro":
            response = (
                "Obrigado 😊 Ainda não consigo confirmar automaticamente a entrega por bairro.\n\n"
                f"Para verificar a entrega no bairro {location_label}, envie o endereço completo ou fale com a atendente."
            )
        else:
            response = (
                "Obrigado 😊 Ainda não consigo confirmar automaticamente a entrega por endereço.\n\n"
                "Para verificar a entrega nesse endereço, fale com a atendente."
            )

        return {
            "intent": "duvida_entrega_retirada",
            "database": {"implemented": False, "message": "Resposta de continuidade para bairro/endereco de entrega.", "data": None},
            "instructions": self.instructions_agent.get_instructions(),
            "cardapio_loaded": bool(self.cardapio_agent.get_cardapio()),
            "rag_results": [],
            "file_info": None,
            "final_response": response,
        }

    def _outside_business_hours_response(self, message: str, state=None) -> str:
        business = get_active_business_settings()
        order_hours = order_hours_summary(business)
        pickup_hours = pickup_hours_summary(business)
        delivery_hours = delivery_hours_summary(business)
        combined_hours = delivery_hours if delivery_hours == pickup_hours else f'entregas: {delivery_hours}; retiradas: {pickup_hours}'
        short_order_hours = f"de {order_hours}" if ':' not in order_hours and not order_hours.startswith('sem ') else f"nos horários: {order_hours}"
        delivery_intent = self._detect_delivery_info_intent(message)
        operational_intent = self._detect_operational_info_intent(message)
        normalized = self._normalize_short_text(message)

        if self._is_human_request(message):
            return self._outside_hours_human_response()
        if delivery_intent:
            return self._outside_hours_delivery_response(delivery_intent)
        if operational_intent == "horario_funcionamento":
            return self._build_business_hours_response(message)
        if operational_intent == "localizacao":
            return self._outside_hours_location_response()
        if operational_intent == "informacoes_gerais":
            return self._outside_hours_general_info_response()
        if self._is_cardapio_followup(message):
            return self._outside_hours_cardapio_response(message)
        if self._is_business_hours_order_attempt(normalized):
            return self._outside_hours_order_block_response()
        if self._has_outside_hours_marker(state):
            return (
                "Ainda estamos fora do horário de atendimento 😊\n\n"
                "Mas posso te passar informações básicas, como horário, entrega, localização e cardápio."
            )
        return (
            "Olá! 😊\n\n"
            "No momento estamos fora do horário de atendimento.\n\n"
            "Pedidos/encomendas:\n"
            f"{order_hours}.\n\n"
            "Entregas e retiradas:\n"
            f"{combined_hours}.\n\n"
            "Por favor, chame dentro do horário para fazer pedidos, consultar cardápios, valores ou informações sobre entrega.\n\n"
            "Se quiser, deixe sua mensagem que a atendente responderá assim que possível."
        )

    def _outside_hours_order_block_response(self) -> str:
        return (
            "No momento estamos fora do horário de atendimento para pedidos.\n\n"
            "Você pode chamar dentro do horário para fazer seu pedido na Marmitaria da Adriana.\n\n"
            f"{self._outside_hours_order_schedule_block()}"
        )

    def _outside_hours_delivery_response(self, intent: str) -> str:
        business = get_active_business_settings()
        if intent == "retirada":
            if not business.aceita_retirada_local:
                return "No momento a retirada no local não está disponível."
            return (
                "Você pode retirar no local, sim 😊\n\n"
                "No momento estamos fora do horário de atendimento, mas você pode chamar dentro do horário para combinar a retirada.\n\n"
                f"{self._outside_hours_order_schedule_block()}"
            )
        if not business.aceita_entrega:
            return "No momento a entrega não está disponível. Se quiser, posso te orientar sobre retirada no local."
        return (
            "Fazemos entrega sim 😊\n\n"
            "No momento estamos fora do horário de atendimento, mas você pode chamar dentro do horário para consultar taxa, região atendida e fazer seu pedido.\n\n"
            "Horários de atendimento:\n\n"
            f"{self._outside_hours_order_schedule_lines()}"
        )

    def _outside_hours_human_response(self) -> str:
        return (
            "No momento estamos fora do horário e não há atendente disponível 😊\n\n"
            "Você pode chamar novamente dentro do horário de atendimento para falar com a equipe da Marmitaria da Adriana.\n\n"
            "Horários:\n\n"
            f"{self._outside_hours_order_schedule_lines()}"
        )

    def _outside_hours_location_response(self) -> str:
        location_response = self._build_location_response()
        return (
            f"{location_response}\n\n"
            "Se precisar de atendimento da equipe, chame dentro do horário."
        )

    def _outside_hours_general_info_response(self) -> str:
        response = self._build_general_info_response()
        return (
            f"{response}\n\n"
            "Pedidos só podem ser feitos dentro do horário de atendimento."
        )

    def _outside_hours_cardapio_response(self, message: str) -> str:
        cardapio_response = self._build_cardapio_response_data(
            message,
            self.cardapio_agent.get_cardapio(),
            respect_business_hours=False,
        )["response"]
        return (
            f"{cardapio_response}\n\n"
            "No momento estamos fora do horário de atendimento. Se quiser pedir, me chame dentro do horário."
        )

    def _outside_hours_order_schedule_lines(self) -> str:
        business = get_active_business_settings()
        return "\n".join(self._build_schedule_lines(business, "pedido"))

    def _outside_hours_order_schedule_block(self) -> str:
        return f"Horários de atendimento:\n\n{self._outside_hours_order_schedule_lines()}"

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
            f"Pedidos/encomendas podem ser feitos em {order_hours_summary()}."
        )

    def _build_acknowledgement_response(self, state) -> str:
        if getattr(state, "status_atendimento", "") == AtendimentoStatus.FORA_HORARIO or not self._is_open_for_orders():
            return "Combinado 😊\nQuando estiver dentro do horário, é só me chamar."
        return "Combinado 😊\nQuando quiser, é só me chamar."

    def _build_future_contact_reservation_response(self, message: str, contact_day: str, requested_day: str) -> str:
        subject = self._build_reservation_subject(message, requested_day)
        contact_hours = order_hours_for_day(contact_day) or f'em {order_hours_summary()}'
        return (
            "Perfeito 😊\n\n"
            f"{self._weekday_with_contact_preposition(contact_day)}, {contact_hours}, você pode me chamar para reservar {subject}.\n\n"
            f"Os pedidos/encomendas são feitos em {order_hours_summary()}."
        )

    def _build_price_response(self, message: str) -> str:
        text = self._normalize_short_text(message)
        lines: list[str] = []

        if "marmitex" in text:
            product = get_order_product("marmitex_individual", only_available=True)
            if product is not None:
                lines.append(f"A marmitex individual custa {format_brl(product['preco'])}.")
            else:
                lines.append("No momento a marmitex individual não está disponível.")

        for people in [2, 3, 4, 5]:
            aliases = {str(people), self._number_word(people)}
            if any(
                f"marmita para {alias} pessoas" in text
                or f"marmita para {alias} pessoa" in text
                for alias in aliases
            ):
                product = get_order_product_by_people(people, only_available=True)
                if product is not None:
                    lines.append(f"A marmita para {people} pessoas custa {format_brl(product['preco'])}.")
                else:
                    lines.append(f"No momento a marmita para {people} pessoas não está disponível.")

        if lines:
            return "\n".join(lines)

        available_products = list_order_products(only_available=True)
        if not available_products:
            return "No momento não há opções de pedido disponíveis no catálogo."

        response_lines = ["Nossos valores são:", ""]
        for product in available_products:
            response_lines.append(f"* {product['nome']}: {format_brl(product['preco'])}")
        response_lines.extend(["", owner_consultation_message()])
        return "\n".join(response_lines)

    def _is_price_followup_context(self, message: str, state) -> bool:
        if state.ultima_intencao != "consultar_valores":
            return False
        text = self._normalize_short_text(message)
        return "marmitex" in text or "marmita" in text

    def _number_word(self, number: int) -> str:
        return {
            2: "duas",
            3: "tres",
            4: "quatro",
            5: "cinco",
        }.get(number, str(number))

    def _is_human_request(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return any(
            term in text
            for term in [
                "tem atendente",
                "ninguem para tirar duvidas",
                "ninguem para tirar duvida",
                "tem alguem",
                "quero falar com alguem",
                "atendente",
                "atendimento humano",
                "falar com alguem",
                "falar com alguém",
                "falar com uma pessoa",
                "falar com pessoa",
                "falar com humano",
            ]
        )

    def _has_outside_hours_marker(self, state) -> bool:
        if state is None:
            return False
        return (getattr(state, "ultima_intencao", "") or "").strip() == "fora_horario_informado"

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

    def _is_cardapio_confirmation_after_offer(self, message: str) -> bool:
        text = self._normalize_short_text(message)
        return text in {
            "sim",
            "quero",
            "eu quero",
            "gostaria",
            "quero sim",
            "pode ser",
            "me mostra",
            "mostrar",
            "pode mostrar",
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
            or self._is_other_day_request(text)
            or bool(self._extract_weekday(text))
            or "cardapio" in text
            or "menu" in text
            or "prato" in text
        )

    def _is_other_day_request(self, normalized_text: str) -> bool:
        return normalized_text in {
            "quero ver outro dia",
            "me mostra outro dia",
            "mostrar outro dia",
            "ver outro dia",
            "outro dia",
        }

    def _is_today_request(self, normalized_text: str) -> bool:
        return normalized_text in {"hoje", "o de hoje", "de hoje", "cardapio de hoje", "menu de hoje"} or "hoje" in normalized_text

    def _build_cardapio_response(self, message: str, cardapio: str, respect_business_hours: bool = True) -> str:
        return self._build_cardapio_response_data(
            message,
            cardapio,
            respect_business_hours=respect_business_hours,
        )["response"]

    def _build_cardapio_response_data(self, message: str, cardapio: str, respect_business_hours: bool = True) -> dict:
        normalized = self._normalize_short_text(message)
        if self._is_weekly_cardapio_request(normalized):
            return {
                "response": self._build_weekly_cardapio_response(cardapio),
                "resolved_day": "",
                "awaiting_day_selection": False,
            }
        if self._is_other_day_request(normalized):
            available_days = self._available_weekdays_from_cardapio(cardapio)
            if available_days:
                day_lines = [
                    f"{self._weekday_to_menu_number(day_name)} - {self._display_weekday(day_name).capitalize()}"
                    for day_name in available_days
                ]
                return {
                    "response": (
                        "Cardápios disponíveis:\n"
                        f"{chr(10).join(day_lines)}\n\n"
                        "Digite o número ou o nome do dia que deseja consultar."
                    ),
                    "resolved_day": "",
                    "awaiting_day_selection": True,
                }

        asserted_today = self._extract_asserted_today_weekday(message or "")
        current_day = self._current_weekday_ptbr()
        if asserted_today and asserted_today != current_day:
            suggested_day = asserted_today
            return {
                "response": (
                    f"{self._system_today_sentence()}\n\n"
                    "Por isso, não há cardápio cadastrado para hoje.\n\n"
                    f"Posso te mostrar o cardápio de {self._display_weekday(suggested_day)} ou de outro dia da semana."
                ),
                "resolved_day": "",
                "awaiting_day_selection": False,
            }

        day = self._extract_weekday(message or "")
        if respect_business_hours and not self._is_open_for_orders() and (not day or self._is_today_request(normalized)):
            return {
                "response": self._cardapio_after_hours_response(),
                "resolved_day": "",
                "awaiting_day_selection": False,
            }

        if not day or self._is_today_request(normalized):
            day = self._current_weekday_ptbr()
            prefix = f"Claro 😊 Hoje é {self._display_weekday(day)}. O cardápio de hoje é:"
        else:
            prefix = f"Claro 😊 O cardápio de {self._display_weekday(day)} é:"

        day_menu = self._extract_day_menu(cardapio, day)
        if not day_menu:
            if not day or self._is_today_request(normalized):
                available_days = self._available_weekdays_from_cardapio(cardapio)
                if available_days:
                    day_lines = [
                        f"{self._weekday_to_menu_number(day_name)} - {self._display_weekday(day_name).capitalize()}"
                        for day_name in available_days
                    ]
                    return {
                        "response": (
                            "Hoje não temos cardápio cadastrado.\n\n"
                            "Cardápios disponíveis:\n"
                            f"{chr(10).join(day_lines)}\n\n"
                            "Digite o número ou o nome do dia que deseja consultar."
                        ),
                        "resolved_day": "",
                        "awaiting_day_selection": True,
                    }
            return {
                "response": "Não encontrei cardápio cadastrado para esse dia. Você deseja consultar outro dia da semana?",
                "resolved_day": "",
                "awaiting_day_selection": False,
            }
        return {
            "response": f"{prefix}\n\n{day_menu}",
            "resolved_day": day,
            "awaiting_day_selection": False,
        }

    def _cardapio_after_hours_response(self) -> str:
        business = get_active_business_settings()
        return (
            "O cardápio de hoje já encerrou junto com o horário de pedidos.\n\n"
            f"Pedidos/encomendas podem ser feitos em {order_hours_summary(business)}.\n"
            f"Entregas: {delivery_hours_summary(business)}.\n"
            f"Retiradas: {pickup_hours_summary(business)}.\n\n"
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
            return "Não encontrei o cardápio semanal cadastrado."

        return "Claro 😊 Esse é o cardápio da semana:\n\n" + "\n\n".join(sections)

    def _display_weekday(self, day: str) -> str:
        return format_day_display(day)

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
            return "Agora, para continuar seu pedido, você deseja marmitex individual ou marmita para quantas pessoas?"
        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA:
            return "Agora, para continuar seu pedido, me diga para quantas pessoas e a marmita."
        if state.aguardando_resposta == "complemento":
            return "Agora, para continuar seu pedido, escolha se deseja adicionar alguma bebida, sobremesa ou adicional."
        if state.aguardando_resposta == "quantidade_complemento":
            return "Agora, para continuar seu pedido, me informe a quantidade do complemento."
        if state.aguardando_resposta == "mais_complementos":
            return "Agora, para continuar seu pedido, me diga se quer mais algum complemento ou se posso seguir."
        if not state.tipo_entrega:
            return "Agora, para continuar seu pedido, você prefere entrega ou retirada no local?"
        if state.tipo_entrega == "entrega" and not state.endereco:
            return "Agora, para continuar seu pedido, por favor, informe o endereço completo para entrega."
        if not state.forma_pagamento:
            return "Agora, para continuar seu pedido, qual será a forma de pagamento? Pix, dinheiro ou cartão?"
        if state.forma_pagamento == "Pix" and state.status_atendimento == AtendimentoStatus.AGUARDANDO_COMPROVANTE:
            return "Agora, para continuar seu pedido, pode enviar o comprovante por aqui."
        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
            return "Seu comprovante já foi recebido e está aguardando conferência."
        return "Agora, para continuar seu pedido, confirme se está tudo certo, por favor."

    def _handle_menu_option(self, menu_option: str) -> str:
        if menu_option == "1":
            return self._start_order_prompt()
        if menu_option == "2":
            return (
                "Claro! Me diga o dia da semana que você quer consultar "
                "(por exemplo: segunda, terça, quarta...)."
            )
        if menu_option == "3":
            return self._product_options_message()
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

    def _build_intent_state_summary(self, state) -> dict:
        return {
            "status_atendimento": state.status_atendimento,
            "ultima_intencao": state.ultima_intencao,
            "aguardando_resposta": state.aguardando_resposta,
            "pedido_atual": {
                "produto": state.produto or None,
                "quantidade": state.quantidade or None,
                "tipo_entrega": state.tipo_entrega or None,
                "endereco": state.endereco or None,
                "forma_pagamento": state.forma_pagamento or None,
            },
        }

    def _generate_final_response(self, context: str, intent: str, has_file: bool, rag_snippets: list[dict]) -> str:
        if not rag_snippets:
            return (
                "Não encontrei dados suficientes nas instruções para responder com segurança. "
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
                "Por segurança, não confirmamos pagamento automaticamente por aqui."
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
        return "Posso te ajudar melhor se você me contar mais detalhes do que precisa."

    def _response_from_rag_rules(self, message: str, cardapio: str, rag_snippets: list[dict]) -> str:
        msg = message.lower()
        rag_text = " ".join(item.get("text", "") for item in rag_snippets).lower()
        normalized_msg = self._normalize_short_text(message)

        if any(term in normalized_msg for term in ["valor", "valores", "preco", "precos", "quanto custa", "custa"]):
            if "marmitex" in normalized_msg or "marmita" in normalized_msg:
                return self._build_price_response(message)

        people_count = self._extract_people_count(msg)
        if people_count is not None:
            if people_count > 5:
                if "acima de 5 pessoas" in rag_text or "mais de 5 pessoas" in rag_text:
                    return owner_consultation_message()
            if 2 <= people_count <= 5:
                value = self._extract_price_for_people(rag_text, people_count)
                if value:
                    return f"A marmita para {people_count} pessoas custa {value}."

        if "cardapio" in normalized_msg:
            if self._is_weekly_cardapio_request(normalized_msg):
                return self._build_weekly_cardapio_response(cardapio)

            day = self._extract_weekday(normalized_msg)
            if not day:
                day = self._current_weekday_ptbr()
            day_menu = self._extract_day_menu(cardapio, day)
            if day_menu:
                return f"Considerando {self._display_weekday(day)}, o cardápio é:\n{day_menu}"
            return "Para eu te informar certinho, pode confirmar qual dia da semana você quer consultar?"

        return ""

    def _handle_cardapio_day_selection_context(
        self,
        message: str,
        phone_key: str,
        file_name: str = "",
        file_mimetype: str = "",
    ) -> dict | None:
        day = self._extract_cardapio_day_selection(message)
        if not day:
            return None

        instructions = self.instructions_agent.get_instructions()
        cardapio = self.cardapio_agent.get_cardapio()
        rag_snippets = self.rag_agent.search(message, top_k=4).get("results", [])
        file_info = self.file_agent.parse_file_info(file_name, file_mimetype) if (file_name or file_mimetype) else None
        cardapio_response_data = self._build_cardapio_response_data(
            day,
            cardapio,
            respect_business_hours=False,
        )
        update_state(
            phone_key,
            status_atendimento=AtendimentoStatus.CONSULTANDO_CARDAPIO,
            ultima_intencao=f"consultar_cardapio:{day}",
            aguardando_resposta="",
        )
        return {
            "intent": "consultando_cardapio",
            "database": {"implemented": False, "message": "Consulta local de cardapio por escolha de dia.", "data": None},
            "instructions": instructions,
            "cardapio_loaded": bool(cardapio),
            "rag_results": rag_snippets,
            "file_info": file_info.__dict__ if file_info else None,
            "final_response": cardapio_response_data["response"],
        }

    def _update_cardapio_state_from_response(self, phone_key: str, response_data: dict) -> None:
        if response_data.get("awaiting_day_selection"):
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.CONSULTANDO_CARDAPIO,
                aguardando_resposta="dia_cardapio",
                ultima_intencao="consultar_cardapio",
            )
            return

        resolved_day = (response_data.get("resolved_day") or "").strip()
        if resolved_day:
            update_state(
                phone_key,
                status_atendimento=AtendimentoStatus.CONSULTANDO_CARDAPIO,
                aguardando_resposta="",
                ultima_intencao=f"consultar_cardapio:{resolved_day}",
            )
            return

        update_state(
            phone_key,
            status_atendimento=AtendimentoStatus.CONSULTANDO_CARDAPIO,
            aguardando_resposta="cardapio",
            ultima_intencao="consultar_cardapio",
        )

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

    def _extract_cardapio_day_selection(self, text: str) -> str:
        normalized = self._normalize_short_text(text)
        day_by_number = self._cardapio_day_number_map()
        if normalized in day_by_number:
            return day_by_number[normalized]
        return self._extract_weekday(text)

    def _extract_delivery_location_details(self, text: str) -> tuple[str, str]:
        original = (text or "").strip()
        normalized = self._normalize_short_text(text)
        if not normalized:
            return "", ""

        bairro_match = re.search(r"\bbairro\s+(.+)$", original, flags=re.IGNORECASE)
        if bairro_match:
            return "bairro", self._format_location_label(bairro_match.group(1))

        address_markers = ["rua", "avenida", "av ", "travessa", "numero", "nº", "cep"]
        if any(marker in normalized for marker in address_markers):
            return "endereco", original

        tokens = normalized.split()
        if 1 <= len(tokens) <= 3 and not any(token.isdigit() for token in tokens):
            return "bairro", self._format_location_label(original)
        return "", ""

    def _extract_future_contact_and_requested_days(self, text: str) -> tuple[str, str]:
        normalized = self._normalize_short_text(text)
        if not normalized:
            return "", ""

        contact_markers = [
            "te envio",
            "envio uma mensagem",
            "mando mensagem",
            "te mando",
            "te chamo",
            "vou te chamar",
            "vou chamar",
            "eu chamo",
            "eu mando",
            "eu te mando",
            "eu te envio",
            "falo com voce",
        ]
        reservation_markers = ["reservar", "pedido", "pedir", "marmitex", "marmita", "cardapio", "menu"]
        if not any(marker in normalized for marker in contact_markers):
            return "", ""
        if not any(marker in normalized for marker in reservation_markers):
            return "", ""

        ordered_days = self._extract_weekdays_in_text_order(text)
        if len(ordered_days) < 2:
            return "", ""
        return ordered_days[0], ordered_days[-1]

    def _extract_weekdays_in_text_order(self, text: str) -> list[str]:
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
        hits: list[tuple[int, str]] = []
        for canonical, values in aliases.items():
            first_pos = None
            for value in values:
                match = re.search(rf"\b{re.escape(self._normalize_short_text(value))}\b", normalized)
                if match and (first_pos is None or match.start() < first_pos):
                    first_pos = match.start()
            if first_pos is not None:
                hits.append((first_pos, canonical))
        hits.sort(key=lambda item: item[0])
        return [day for _, day in hits]

    def _build_reservation_subject(self, message: str, requested_day: str) -> str:
        normalized = self._normalize_short_text(message)
        displayed_day = self._display_weekday(requested_day)
        if "marmitex" in normalized:
            return f"a marmitex de {displayed_day}"
        if "marmita" in normalized:
            return f"a marmita de {displayed_day}"
        return f"o cardápio de {displayed_day}"

    def _weekday_with_contact_preposition(self, day: str) -> str:
        displayed_day = self._display_weekday(day)
        if day in {"sabado", "domingo"}:
            return f"No {displayed_day}"
        return f"Na {displayed_day}"

    def _weekday_short_with_contact_preposition(self, day: str) -> str:
        displayed_day = self._display_weekday(day).split("-")[0]
        if day in {"sabado", "domingo"}:
            return f"no {displayed_day}"
        return f"na {displayed_day}"

    def _format_location_label(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", (text or "").strip(" .,:;-")).strip()
        return cleaned.title()

    def _cardapio_day_number_map(self) -> dict[str, str]:
        return {
            "1": "segunda-feira",
            "2": "terca-feira",
            "3": "quarta-feira",
            "4": "quinta-feira",
            "5": "sexta-feira",
            "6": "sabado",
        }

    def _weekday_to_menu_number(self, day: str) -> str:
        reverse_map = {value: key for key, value in self._cardapio_day_number_map().items()}
        return reverse_map.get(day, "")

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

    def _extract_asserted_today_weekday(self, text: str) -> str:
        normalized = self._normalize_short_text(text)
        if "hoje" not in normalized:
            return ""
        if not any(
            token in normalized
            for token in ["hoje e", "hoje eh", "mas hoje e", "mas hoje eh", "hoje e", "hoje"]
        ):
            return ""
        return self._extract_weekday(normalized)

    def _is_reservation_intent(self, normalized_text: str) -> bool:
        return any(term in normalized_text for term in ["reservar", "reserva", "encomenda", "encomendar"])

    def _mentions_pickup(self, normalized_text: str) -> bool:
        return any(term in normalized_text for term in ["retirar", "retirada", "buscar", "vou buscar"])

    def _mentions_time_11h(self, normalized_text: str) -> bool:
        compact = normalized_text.replace(" ", "")
        return "11h" in compact or "11:00" in compact or "as11" in compact or "às11" in compact

    def _system_today_sentence(self) -> str:
        current_day = self._current_weekday_ptbr()
        current_date = timezone.localdate().strftime("%d/%m/%Y")
        return f"Pelo sistema, hoje é {self._display_weekday(current_day)}, {current_date}."

    def _mark_last_consulted_cardapio_day(self, telefone: str, message: str) -> None:
        day = self._extract_weekday(message or "")
        normalized = self._normalize_short_text(message or "")
        if not day and self._is_today_request(normalized):
            day = self._current_weekday_ptbr()
        if not day:
            return
        update_state(telefone, ultima_intencao=f"consultar_cardapio:{day}")

    def _extract_last_consulted_day_from_state(self, state) -> str:
        if state is None:
            return ""
        marker = (getattr(state, "ultima_intencao", "") or "").strip()
        prefix = "consultar_cardapio:"
        if not marker.startswith(prefix):
            return ""
        return marker[len(prefix):].strip()

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

    def _available_weekdays_from_cardapio(self, cardapio: str) -> list[str]:
        if not cardapio:
            return []
        headings = re.findall(r"##\s*([^\n]+)", cardapio, flags=re.IGNORECASE)
        found: list[str] = []
        for heading in headings:
            day = self._extract_weekday(heading)
            if day and day not in found:
                found.append(day)
        return found


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

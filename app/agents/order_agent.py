import re
import unicodedata
from dataclasses import asdict

from .conversation_state import AtendimentoStatus, get_or_create_state, reset_state, update_state
from app.order_catalog import format_brl, get_order_product, get_order_product_by_people, get_order_product_choices, list_order_products
from .payment_proof_agent import PaymentProofAgent

NUMBER_WORDS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
}


class OrderAgent:
    """Controla montagem de pedido durante a conversa."""

    def __init__(self) -> None:
        self.payment_proof_agent = PaymentProofAgent()

    def process_message(
        self,
        telefone: str,
        message: str,
        structured_analysis: dict | None = None,
        file_name: str = "",
        file_mimetype: str = "",
    ) -> dict:
        structured_result = self.process_structured_input(
            telefone=telefone,
            message=message,
            structured_analysis=structured_analysis,
        )
        if structured_result is not None:
            return structured_result

        state = get_or_create_state(telefone)
        text = (message or "").strip().lower()
        normalized = self._normalize(text)
        in_order = state.ultima_intencao == "fazer_pedido" or state.status_atendimento != AtendimentoStatus.INICIO

        if self._is_cancel_request(normalized):
            reset_state(telefone)
            return {
                "state": asdict(get_or_create_state(telefone)),
                "pricing": {
                    "can_calculate": False,
                    "needs_owner": False,
                    "unit_price": 0.0,
                    "total_price": 0.0,
                },
                "next_question": "",
                "response": "Pedido cancelado. Se precisar de algo mais, e so me chamar.",
            }

        if self._is_waiting_marmita_type(state):
            type_choice = self._extract_marmita_type_choice(normalized)
            if type_choice is None:
                clarification = (
                    "Nao consegui identificar o tipo. "
                    "Voce deseja marmitex individual ou marmita para 2, 3, 4 ou 5 pessoas?"
                )
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": False,
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": clarification,
                    "response": clarification,
                }

            qty = max(1, int(state.quantidade or 1))
            item = self._make_item_from_key(type_choice, qty)
            if item is None:
                return self._catalog_unavailable_response(telefone, "marmita selecionada")
            return self._apply_item_with_current_delivery_context(telefone, [item])

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_PRODUTO and normalized.isdigit():
            return self._handle_product_menu_choice(telefone, normalized)

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_QUANTIDADE and state.produto == "marmitex_individual":
            qty = self._to_int(normalized)
            if qty:
                item = self._make_item("marmitex individual", "marmitex_individual", qty)
                if item is None:
                    return self._catalog_unavailable_response(telefone, "Marmitex individual")
                return self._apply_order_items(telefone, [item])

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA:
            people = self._extract_people_count_for_pending_family(normalized)
            if people:
                if people > 5:
                    update_state(
                        telefone,
                        status_atendimento=AtendimentoStatus.ENCAMINHAR_ATENDENTE,
                        aguardando_resposta="consulta_proprietaria",
                    )
                    return {
                        "state": asdict(get_or_create_state(telefone)),
                        "pricing": {
                            "can_calculate": False,
                            "needs_owner": True,
                            "unit_price": 0.0,
                            "total_price": 0.0,
                        },
                        "next_question": "Para pedidos acima de 5 pessoas, preciso consultar a proprietaria.",
                        "response": "Para pedidos acima de 5 pessoas, preciso consultar a proprietaria para confirmar o valor certinho.",
                    }
                if people in {2, 3, 4, 5}:
                    pending_items = list(state.itens_pendentes or [])
                    item = self._make_item(
                        produto=f"marmita para {people} pessoas",
                        produto_key=f"marmita_{people}_pessoas",
                        quantidade=max(1, int(state.quantidade or 1)),
                    )
                    if item is None:
                        return self._catalog_unavailable_response(telefone, f"Marmita para {people} pessoas")
                    pending_items.append(item)
                    return self._apply_order_items(telefone, pending_items, clear_pending=True)
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "Essa marmita e para quantas pessoas? Temos opcoes para 2, 3, 4 ou 5 pessoas.",
                "response": "Essa marmita e para quantas pessoas? Temos opcoes para 2, 3, 4 ou 5 pessoas.",
            }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_PAGAMENTO:
            payment_choice = self._extract_payment(text)
            if payment_choice:
                update_state(telefone, forma_pagamento=payment_choice)
                refreshed = get_or_create_state(telefone)
                pricing = {
                    "can_calculate": bool(refreshed.valor_total),
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                }
                next_question = self._next_question(refreshed, pricing)
                response = self._build_response(get_or_create_state(telefone), pricing, next_question)
                return {
                    "state": asdict(get_or_create_state(telefone)),
                    "pricing": pricing,
                    "next_question": next_question,
                    "response": response,
                }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA:
            if self._is_cancel_request(normalized):
                reset_state(telefone)
                return {
                    "state": asdict(get_or_create_state(telefone)),
                    "pricing": {
                        "can_calculate": False,
                        "needs_owner": False,
                        "unit_price": 0.0,
                        "total_price": 0.0,
                    },
                    "next_question": "",
                    "response": "Pedido cancelado. Se precisar de algo mais, e so me chamar.",
                }

            changed_items = self._extract_order_items(text)
            if changed_items["items"] and self._is_explicit_order_request(normalized):
                return self._apply_order_items(telefone, changed_items["items"])

            if changed_items["incomplete_family"] and self._is_explicit_order_request(normalized):
                update_state(
                    telefone,
                    ultima_intencao="fazer_pedido",
                    status_atendimento=AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA,
                    itens_pendentes=changed_items["items"],
                    quantidade=changed_items["incomplete_family_quantity"],
                    aguardando_resposta="pessoas_marmita",
                )
                refreshed = get_or_create_state(telefone)
                partial = self._build_partial_items_text(refreshed.itens_pendentes)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.itens_pendentes),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": round(sum(item["subtotal"] for item in refreshed.itens_pendentes), 2),
                    },
                    "next_question": "Essa marmita e para quantas pessoas? Temos opcoes para 2, 3, 4 ou 5 pessoas.",
                    "response": (
                        f"{partial}\n\n" if partial else ""
                    ) + "Essa marmita e para quantas pessoas? Temos opcoes para 2, 3, 4 ou 5 pessoas.",
                }

            if self._is_delivery_fee_question(normalized):
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": (
                        "Voce prefere:\n1 - Entrega\n2 - Retirada no local\n\n"
                        "Entregas e retiradas acontecem das 11h às 13h."
                    ),
                    "response": (
                        "A taxa de entrega depende do endereco. "
                        "Se voce escolher entrega, me envie o endereco que confirmamos certinho.\n\n"
                        "Voce prefere:\n1 - Entrega\n2 - Retirada no local\n\n"
                        "Entregas e retiradas acontecem das 11h às 13h."
                    ),
                }
            if self._is_delivery_choice(normalized):
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    status_atendimento=AtendimentoStatus.AGUARDANDO_ENDERECO,
                    aguardando_resposta="endereco",
                )
                refreshed = get_or_create_state(telefone)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": "Perfeito 😊 Me informe o endereco de entrega, por favor.",
                    "response": "Perfeito 😊 Me informe o endereco de entrega, por favor.",
                }
            if self._is_pickup_choice(normalized):
                update_state(
                    telefone,
                    tipo_entrega="retirada",
                    endereco="retirada no local",
                    status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                    aguardando_resposta="forma_pagamento",
                )
                refreshed = get_or_create_state(telefone)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": "Qual sera a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartao",
                    "response": (
                        "Perfeito 😊 Vou marcar como retirada no local.\n\n"
                        "Qual sera a forma de pagamento?\n"
                        "1 - Pix\n2 - Dinheiro\n3 - Cartao"
                    ),
                }
            if self._looks_like_address(text):
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    endereco=message.strip(),
                    status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                    aguardando_resposta="forma_pagamento",
                )
                refreshed = get_or_create_state(telefone)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": "Qual sera a forma de pagamento? Pix, dinheiro ou cartao?",
                    "response": "Perfeito 😊 Endereco anotado. Qual sera a forma de pagamento? Pix, dinheiro ou cartao?",
                }
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "Voce prefere: 1 - Entrega 2 - Retirada no local",
                "response": (
                    "Voce prefere:\n"
                    "1 - Entrega\n"
                    "2 - Retirada no local\n\n"
                    "Entregas e retiradas acontecem das 11h às 13h."
                ),
            }

        if self._is_delivery_fee_question(normalized):
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "",
                "response": (
                    "A taxa de entrega depende do endereco. "
                    "Me envie o endereco de entrega para confirmarmos o valor certinho."
                ),
            }

        explicit_order_request = self._is_explicit_order_request(normalized)
        if (
            self._is_price_consultation(normalized) or self._is_price_followup(normalized, state)
        ) and not explicit_order_request:
            response = self._build_price_consultation_response(normalized, in_order=in_order)
            update_state(
                telefone,
                ultima_intencao="consultar_valores",
                status_atendimento=AtendimentoStatus.INICIO if not state.itens_pedido else state.status_atendimento,
            )
            return {
                "state": asdict(get_or_create_state(telefone)),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "",
                "response": response,
            }

        if self._is_local_pickup(normalized):
            update_state(
                telefone,
                tipo_entrega="retirada",
                endereco="retirada no local",
                status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                aguardando_resposta="forma_pagamento",
                ultima_intencao="fazer_pedido",
            )
            refreshed = get_or_create_state(telefone)
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": bool(refreshed.valor_total),
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                },
                "next_question": "Qual sera a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartao",
                "response": (
                    "Perfeito 😊 Vou marcar como retirada no local.\n\n"
                    "Qual sera a forma de pagamento?\n"
                    "1 - Pix\n2 - Dinheiro\n3 - Cartao"
                ),
            }

        if self._is_total_question(text) and state.produto and state.quantidade and state.valor_total > 0:
            waiting_status = AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA
            waiting_question = (
                "Voce prefere:\n1 - Entrega\n2 - Retirada no local\n\n"
                "Entregas e retiradas acontecem das 11h às 13h."
            )
            if state.tipo_entrega == "entrega":
                waiting_status = AtendimentoStatus.AGUARDANDO_ENDERECO
                waiting_question = "Pode me informar o endereco de entrega, por favor?"
            elif state.tipo_entrega == "retirada":
                waiting_status = AtendimentoStatus.AGUARDANDO_PAGAMENTO
                waiting_question = "Qual sera a forma de pagamento? Pix, dinheiro ou cartao?"
            update_state(telefone, status_atendimento=waiting_status)
            refreshed = get_or_create_state(telefone)
            total = f"R$ {refreshed.valor_total:.2f}".replace(".", ",")
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": True,
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                },
                "next_question": waiting_question,
                "response": (
                    f"O total do seu pedido e {total}.\n"
                    f"{waiting_question}"
                ),
            }

        items_data = self._extract_order_items(text)
        if items_data["needs_owner"]:
            update_state(
                telefone,
                ultima_intencao="fazer_pedido",
                status_atendimento=AtendimentoStatus.ENCAMINHAR_ATENDENTE,
                aguardando_resposta="consulta_proprietaria",
            )
            refreshed = get_or_create_state(telefone)
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": False,
                    "needs_owner": True,
                    "unit_price": 0.0,
                    "total_price": 0.0,
                },
                "next_question": (
                    "Para pedidos acima de 5 pessoas, preciso consultar a proprietaria "
                    "do estabelecimento para confirmar o valor certinho."
                ),
                "response": (
                    "Para pedidos acima de 5 pessoas, preciso consultar a proprietaria "
                    "do estabelecimento para confirmar o valor certinho."
                ),
            }

        if items_data["incomplete_family"]:
            update_state(
                telefone,
                ultima_intencao="fazer_pedido",
                status_atendimento=AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA,
                itens_pendentes=items_data["items"],
                quantidade=items_data["incomplete_family_quantity"],
                aguardando_resposta="pessoas_marmita",
            )
            refreshed = get_or_create_state(telefone)
            partial = self._build_partial_items_text(refreshed.itens_pendentes)
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": bool(refreshed.itens_pendentes),
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": round(sum(item["subtotal"] for item in refreshed.itens_pendentes), 2),
                },
                "next_question": "Essa marmita e para quantas pessoas? Temos opcoes para 2, 3, 4 ou 5 pessoas.",
                "response": (
                    f"{partial}\n\n" if partial else ""
                ) + "Essa marmita e para quantas pessoas? Temos opcoes para 2, 3, 4 ou 5 pessoas.",
            }

        if items_data["items"]:
            return self._apply_order_items(telefone, items_data["items"])

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM:
            if self._is_positive_confirmation(text):
                update_state(
                    telefone,
                    status_atendimento=AtendimentoStatus.AGUARDANDO_ENDERECO,
                    aguardando_resposta="endereco",
                )
                refreshed = get_or_create_state(telefone)
                total = f"R$ {refreshed.valor_total:.2f}".replace(".", ",")
                produto = self._human_product_name(refreshed.produto, refreshed.quantidade)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": True,
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": "Pode me informar o endereco de entrega, por favor?",
                    "response": (
                        "Perfeito 😊\n\n"
                        f"Entao ficou:\n{produto}\nTotal: {total}\n\n"
                        "Agora me informe o endereco de entrega, por favor."
                    ),
                }
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "Voce confirma esse item para eu continuar o pedido?",
                "response": "Voce confirma esse item para eu continuar o pedido?",
            }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_COMPROVANTE:
            proof_analysis = self.payment_proof_agent.analyze(
                text=text,
                file_name=file_name,
                mimetype=file_mimetype,
            )
            if proof_analysis["received"]:
                update_state(
                    telefone,
                    status_atendimento=AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
                    aguardando_resposta="conferencia_pagamento",
                )
                refreshed = get_or_create_state(telefone)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": True,
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": "O comprovante sera conferido antes da confirmacao do pedido.",
                    "response": self._build_payment_proof_received_response(refreshed),
                }
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "Envie o comprovante por imagem, PDF ou texto do comprovante.",
                "response": (
                    "Ainda preciso receber o comprovante para seguir com a conferencia do pagamento.\n\n"
                    "Pode enviar por aqui como imagem, PDF ou texto do comprovante. "
                    "Se preferir cancelar, digite cancelar."
                ),
            }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO:
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "Aguarde a conferencia do comprovante.",
                "response": (
                    "Seu comprovante ja foi recebido e esta aguardando conferencia. "
                    "Assim que for validado, o pedido pode ser confirmado pela equipe.\n\n"
                    "Se quiser fazer outro pedido, pode me dizer: novo pedido."
                ),
            }

        if self._wants_to_order(text):
            update_state(
                telefone,
                ultima_intencao="fazer_pedido",
                status_atendimento=AtendimentoStatus.FAZENDO_PEDIDO,
            )

        parsed = self._parse_order_info(text)
        if parsed["produto"]:
            update_state(telefone, produto=parsed["produto"])
        if parsed["quantidade"] is not None:
            update_state(telefone, quantidade=parsed["quantidade"])

        if not parsed["produto"] and parsed["quantidade"] is not None:
            update_state(telefone, produto="marmitex_individual")

        if self._looks_like_address(text):
            update_state(telefone, tipo_entrega="entrega", endereco=message.strip())

        payment = self._extract_payment(text)
        if payment:
            update_state(telefone, forma_pagamento=payment)

        state = get_or_create_state(telefone)
        if state.itens_pedido and state.valor_total > 0:
            pricing = {
                "can_calculate": True,
                "needs_owner": False,
                "unit_price": state.valor_unitario,
                "total_price": state.valor_total,
            }
        else:
            pricing = self._calculate_price(state.produto, state.quantidade)

        if pricing["can_calculate"] and not state.itens_pedido:
            update_state(
                telefone,
                valor_unitario=pricing["unit_price"],
                valor_total=pricing["total_price"],
            )

        state = get_or_create_state(telefone)
        next_question = self._next_question(state, pricing)
        response = self._build_response(state, pricing, next_question)

        aguardando = self._awaiting_field(state, pricing)
        update_state(telefone, aguardando_resposta=aguardando)

        return {
            "state": asdict(get_or_create_state(telefone)),
            "pricing": pricing,
            "next_question": next_question,
            "response": response,
        }

    def process_structured_input(self, telefone: str, message: str, structured_analysis: dict | None) -> dict | None:
        if not structured_analysis:
            return None

        intencao = (structured_analysis.get("intencao") or "").strip().lower()
        confianca = float(structured_analysis.get("confianca") or 0.0)
        precisa_confirmacao = bool(structured_analysis.get("precisa_confirmacao"))

        if intencao in {"", "desconhecida"} or confianca < 0.55 or precisa_confirmacao:
            return None

        state = get_or_create_state(telefone)
        in_order = state.ultima_intencao == "fazer_pedido" or state.status_atendimento != AtendimentoStatus.INICIO

        produto_key = self._structured_product_to_key(
            produto=structured_analysis.get("produto"),
            tipo_marmita=structured_analysis.get("tipo_marmita"),
        )
        quantidade = structured_analysis.get("quantidade")
        tipo_entrega = (structured_analysis.get("tipo_entrega") or "").strip().lower()
        endereco = (structured_analysis.get("endereco") or "").strip()

        if intencao == "alterar_quantidade":
            if not in_order:
                return None
            parsed_qty = self._to_int(str(quantidade)) if quantidade is not None else None
            if parsed_qty is None:
                return None
            if parsed_qty < 1:
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": "Me informe uma quantidade valida (minimo 1).",
                    "response": "Me informe uma quantidade valida (minimo 1).",
                }
            current_key = state.produto or "marmitex_individual"
            item = self._make_item_from_key(current_key, parsed_qty)
            if item is None:
                return self._catalog_unavailable_response(telefone, "item selecionado")
            return self._apply_order_items(telefone, [item])

        if intencao == "informar_retirada" and in_order:
            update_state(
                telefone,
                tipo_entrega="retirada",
                endereco="retirada no local",
                status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                aguardando_resposta="forma_pagamento",
                ultima_intencao="fazer_pedido",
            )
            refreshed = get_or_create_state(telefone)
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": bool(refreshed.valor_total),
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                },
                "next_question": "Qual sera a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartao",
                "response": (
                    "Perfeito 😊 Vou marcar como retirada no local.\n\n"
                    "Qual sera a forma de pagamento?\n"
                    "1 - Pix\n2 - Dinheiro\n3 - Cartao"
                ),
            }
        if intencao == "informar_retirada" and not in_order and "marmita" in self._normalize(message):
            qty = self._to_int(str(quantidade)) if quantidade is not None else None
            update_state(
                telefone,
                ultima_intencao="fazer_pedido",
                status_atendimento=AtendimentoStatus.AGUARDANDO_PRODUTO,
                aguardando_resposta="tipo_marmita",
                produto="marmita",
                quantidade=max(1, int(qty or 1)),
                tipo_entrega="retirada",
            )
            refreshed = get_or_create_state(telefone)
            clarification = "Voce deseja marmitex individual ou marmita para 2, 3, 4 ou 5 pessoas?"
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": False,
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                },
                "next_question": clarification,
                "response": clarification,
            }

        if intencao in {"informar_endereco", "informar_entrega"} and in_order:
            if tipo_entrega == "entrega" and not endereco:
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": "Pode me informar o endereco de entrega, por favor?",
                    "response": "Pode me informar o endereco de entrega, por favor?",
                }
            if endereco:
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    endereco=endereco,
                    status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                    aguardando_resposta="forma_pagamento",
                    ultima_intencao="fazer_pedido",
                )
                refreshed = get_or_create_state(telefone)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": "Qual sera a forma de pagamento? Pix, dinheiro ou cartao?",
                    "response": "Perfeito 😊 Endereco anotado. Qual sera a forma de pagamento? Pix, dinheiro ou cartao?",
                }

        if intencao != "fazer_pedido":
            return None

        resolved_qty = self._to_int(str(quantidade)) if quantidade is not None else None
        if resolved_qty is not None and resolved_qty < 1:
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "Me informe uma quantidade valida (minimo 1).",
                "response": "Me informe uma quantidade valida (minimo 1).",
            }

        if self._is_ambiguous_marmita_request(
            produto=structured_analysis.get("produto"),
            tipo_marmita=structured_analysis.get("tipo_marmita"),
        ):
            qty = resolved_qty or state.quantidade or 1
            update_fields = {
                "ultima_intencao": "fazer_pedido",
                "status_atendimento": AtendimentoStatus.AGUARDANDO_PRODUTO,
                "aguardando_resposta": "tipo_marmita",
                "produto": "marmita",
                "quantidade": qty,
            }
            if tipo_entrega in {"entrega", "retirada"}:
                update_fields["tipo_entrega"] = tipo_entrega
            if endereco:
                update_fields["endereco"] = endereco
            update_state(telefone, **update_fields)
            refreshed = get_or_create_state(telefone)
            clarification = "Voce deseja marmitex individual ou marmita para 2, 3, 4 ou 5 pessoas?"
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": False,
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                },
                "next_question": clarification,
                "response": clarification,
            }

        if produto_key is None:
            return None

        if produto_key.startswith("marmita_") and produto_key.endswith("_pessoas"):
            people = self._extract_people_from_key(produto_key)
            if people and people > 5:
                return None

        qty = resolved_qty or 1
        if produto_key.startswith("marmita_") and produto_key.endswith("_pessoas"):
            people_size = self._extract_people_from_key(produto_key)
            if (
                people_size
                and resolved_qty == people_size
                and self._normalize(structured_analysis.get("produto") or "") == "marmita"
                and bool(structured_analysis.get("tipo_marmita"))
            ):
                qty = 1
        item = self._make_item_from_key(produto_key, qty)
        if item is None:
            human_name = "marmita selecionada" if produto_key != "marmitex_individual" else "marmitex individual"
            return self._catalog_unavailable_response(telefone, human_name)

        result = self._apply_order_items(telefone, [item])
        if tipo_entrega == "retirada":
            update_state(
                telefone,
                tipo_entrega="retirada",
                endereco="retirada no local",
                status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                aguardando_resposta="forma_pagamento",
            )
            refreshed = get_or_create_state(telefone)
            result["state"] = asdict(refreshed)
            result["pricing"]["unit_price"] = refreshed.valor_unitario
            result["pricing"]["total_price"] = refreshed.valor_total
            result["next_question"] = "Qual sera a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartao"
            result["response"] = (
                self._build_items_summary_response(
                    items=refreshed.itens_pedido,
                    total=refreshed.valor_total,
                    ask_address=False,
                )
                + "\n\nPerfeito 😊 Vou marcar como retirada no local.\n\n"
                + "Qual sera a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartao"
            )
        elif tipo_entrega == "entrega":
            if endereco:
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    endereco=endereco,
                    status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                    aguardando_resposta="forma_pagamento",
                )
                refreshed = get_or_create_state(telefone)
                result["state"] = asdict(refreshed)
                result["pricing"]["unit_price"] = refreshed.valor_unitario
                result["pricing"]["total_price"] = refreshed.valor_total
                result["next_question"] = "Qual sera a forma de pagamento? Pix, dinheiro ou cartao?"
                result["response"] = (
                    self._build_items_summary_response(
                        items=refreshed.itens_pedido,
                        total=refreshed.valor_total,
                        ask_address=False,
                    )
                    + "\n\nPerfeito 😊 Endereco anotado. Qual sera a forma de pagamento? Pix, dinheiro ou cartao?"
                )
            else:
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    status_atendimento=AtendimentoStatus.AGUARDANDO_ENDERECO,
                    aguardando_resposta="endereco",
                )
                refreshed = get_or_create_state(telefone)
                result["state"] = asdict(refreshed)
                result["pricing"]["unit_price"] = refreshed.valor_unitario
                result["pricing"]["total_price"] = refreshed.valor_total
                result["next_question"] = "Perfeito 😊 Me informe o endereco de entrega, por favor."
                result["response"] = (
                    self._build_items_summary_response(
                        items=refreshed.itens_pedido,
                        total=refreshed.valor_total,
                        ask_address=False,
                    )
                    + "\n\nPerfeito 😊 Me informe o endereco de entrega, por favor."
                )
        return result

    def _make_item_from_key(self, produto_key: str, quantidade: int) -> dict | None:
        qty = max(1, int(quantidade or 1))
        if produto_key == "marmitex_individual":
            return self._make_item("marmitex individual", "marmitex_individual", qty)
        people = self._extract_people_from_key(produto_key)
        if not people:
            return None
        return self._make_item(f"marmita para {people} pessoas", produto_key, qty)

    def _extract_people_from_key(self, produto_key: str) -> int | None:
        match = re.match(r"marmita_(\d+)_pessoas$", produto_key or "")
        if not match:
            return None
        return int(match.group(1))

    def _structured_product_to_key(self, produto: str | None, tipo_marmita: str | None) -> str | None:
        p = self._normalize(produto or "")
        t = self._normalize(tipo_marmita or "")
        if "marmitex" in p or t == "individual":
            return "marmitex_individual"
        if "marmita" in p:
            if t.endswith("_pessoas"):
                people = self._to_int(t.replace("_pessoas", ""))
                if people and 2 <= people <= 5:
                    return f"marmita_{people}_pessoas"
            match = re.search(r"(\d+)", t)
            if match:
                people = int(match.group(1))
                if 2 <= people <= 5:
                    return f"marmita_{people}_pessoas"
            return None
        return None

    def _is_ambiguous_marmita_request(self, produto: str | None, tipo_marmita: str | None) -> bool:
        p = self._normalize(produto or "")
        t = self._normalize(tipo_marmita or "")
        if "marmitex" in p:
            return False
        if "marmita" not in p:
            return False
        return t in {"", "marmita"}

    def _is_waiting_marmita_type(self, state) -> bool:
        return (
            state.status_atendimento == AtendimentoStatus.AGUARDANDO_PRODUTO
            and state.aguardando_resposta == "tipo_marmita"
            and self._normalize(state.produto or "") == "marmita"
        )

    def _extract_marmita_type_choice(self, normalized_text: str) -> str | None:
        if any(term in normalized_text for term in ["marmitex", "individual"]):
            return "marmitex_individual"

        match = re.search(r"\b([2-5])\b", normalized_text)
        if match:
            people = int(match.group(1))
            return f"marmita_{people}_pessoas"
        return None

    def _apply_item_with_current_delivery_context(self, telefone: str, items: list[dict]) -> dict:
        result = self._apply_order_items(telefone, items)
        refreshed = get_or_create_state(telefone)

        if refreshed.tipo_entrega == "retirada":
            update_state(
                telefone,
                endereco="retirada no local",
                status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO,
                aguardando_resposta="forma_pagamento",
            )
            current = get_or_create_state(telefone)
            result["state"] = asdict(current)
            result["pricing"]["unit_price"] = current.valor_unitario
            result["pricing"]["total_price"] = current.valor_total
            result["next_question"] = "Qual sera a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartao"
            result["response"] = (
                self._build_items_summary_response(
                    items=current.itens_pedido,
                    total=current.valor_total,
                    ask_address=False,
                )
                + "\n\nPerfeito 😊 Vou marcar como retirada no local.\n\n"
                + "Qual sera a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartao"
            )
            return result

        if refreshed.tipo_entrega == "entrega" and not refreshed.endereco:
            update_state(
                telefone,
                status_atendimento=AtendimentoStatus.AGUARDANDO_ENDERECO,
                aguardando_resposta="endereco",
            )
            current = get_or_create_state(telefone)
            result["state"] = asdict(current)
            result["pricing"]["unit_price"] = current.valor_unitario
            result["pricing"]["total_price"] = current.valor_total
            result["next_question"] = "Perfeito 😊 Me informe o endereco de entrega, por favor."
            result["response"] = (
                self._build_items_summary_response(
                    items=current.itens_pedido,
                    total=current.valor_total,
                    ask_address=False,
                )
                + "\n\nPerfeito 😊 Me informe o endereco de entrega, por favor."
            )
        return result

    def _wants_to_order(self, text: str) -> bool:
        return any(k in text for k in ["pedido", "pedir", "quero", "comprar", "marmita", "marmitex"])

    def _handle_product_menu_choice(self, telefone: str, choice: str) -> dict:
        available_choices = get_order_product_choices()
        selected_choice = next((item for item in available_choices if item["choice"] == choice), None)
        if selected_choice is None:
            return {
                "state": asdict(get_or_create_state(telefone)),
                "pricing": {
                    "can_calculate": False,
                    "needs_owner": False,
                    "unit_price": 0.0,
                    "total_price": 0.0,
                },
                "next_question": self._product_selection_prompt(),
                "response": self._product_selection_prompt(),
            }

        if selected_choice["key"] == "marmitex_individual":
            update_state(
                telefone,
                ultima_intencao="fazer_pedido",
                produto="marmitex_individual",
                status_atendimento=AtendimentoStatus.AGUARDANDO_QUANTIDADE,
                aguardando_resposta="quantidade",
            )
            state = get_or_create_state(telefone)
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": False,
                    "needs_owner": False,
                    "unit_price": float(selected_choice["preco"]),
                    "total_price": 0.0,
                },
                "next_question": "Quantas marmitex individuais voce deseja?",
                "response": "Perfeito 😊 Quantas marmitex individuais voce deseja?",
            }

        people = int(selected_choice["people_count"])
        item = self._make_item(
            produto=f"marmita para {people} pessoas",
            produto_key=f"marmita_{people}_pessoas",
            quantidade=1,
        )
        if item is None:
            return self._catalog_unavailable_response(telefone, selected_choice["nome"])
        return self._apply_order_items(telefone, [item])

    def _make_item(self, produto: str, produto_key: str, quantidade: int) -> dict | None:
        catalog_item = get_order_product(produto_key, only_available=True)
        if catalog_item is None:
            return None
        unit = float(catalog_item["preco"])
        return {
            "produto": produto,
            "produto_key": produto_key,
            "quantidade": quantidade,
            "valor_unitario": unit,
            "subtotal": round(quantidade * unit, 2),
        }

    def _apply_order_items(self, telefone: str, items: list[dict], clear_pending: bool = False) -> dict:
        total_price = round(sum(item["subtotal"] for item in items), 2)
        first = items[0]
        pending_fields = {}
        if clear_pending:
            pending_fields = {"itens_pendentes": []}
        update_state(
            telefone,
            ultima_intencao="fazer_pedido",
            status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
            itens_pedido=items,
            produto=first["produto_key"],
            quantidade=first["quantidade"],
            valor_unitario=first["valor_unitario"],
            valor_total=total_price,
            aguardando_resposta="tipo_entrega",
            **pending_fields,
        )
        refreshed = get_or_create_state(telefone)
        response = self._build_items_summary_response(
            items=refreshed.itens_pedido,
            total=refreshed.valor_total,
            ask_address=not bool(refreshed.tipo_entrega),
        )
        return {
            "state": asdict(refreshed),
            "pricing": {
                "can_calculate": True,
                "needs_owner": False,
                "unit_price": refreshed.valor_unitario,
                "total_price": refreshed.valor_total,
            },
            "next_question": (
                "Voce prefere:\n1 - Entrega\n2 - Retirada no local\n\n"
                "Entregas e retiradas acontecem das 11h às 13h."
            ),
            "response": response,
        }

    def _is_explicit_order_request(self, normalized_text: str) -> bool:
        if not any(product in normalized_text for product in ["marmitex", "marmita"]):
            return False

        price_only_terms = [
            "quero saber",
            "queria saber",
            "gostaria de saber",
            "qual o valor",
            "quais os valores",
            "qual os valores",
            "me informa os valores",
            "me passa os precos",
            "tabela de preco",
        ]
        if any(term in normalized_text for term in price_only_terms):
            return False

        order_terms = [
            "quero",
            "vou querer",
            "pode ser",
            "separa",
            "reservar",
            "reserva",
            "vou pedir",
            "fazer pedido",
            "fazer um pedido",
        ]
        if not any(term in normalized_text for term in order_terms):
            return False

        quantity_pattern = r"\b(\d+|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez)\b"
        return bool(re.search(quantity_pattern, normalized_text))

    def _is_cancel_request(self, normalized_text: str) -> bool:
        return any(term in normalized_text for term in ["cancelar", "cancela", "quero cancelar", "cancelar pedido"])

    def _is_positive_confirmation(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        positive_terms = {
            "sim",
            "isso",
            "isso mesmo",
            "e isso",
            "correto",
            "confirmo",
            "pode ser",
            "ta certo",
            "tá certo",
            "beleza",
            "ok",
            "certo",
        }
        if normalized in positive_terms:
            return True
        if "isso" in normalized and ("mesmo" in normalized or "mesm" in normalized):
            return True
        return False

    def _normalize(self, text: str) -> str:
        raw = (text or "").strip().lower().replace("9", "o")
        raw = "".join(ch for ch in unicodedata.normalize("NFD", raw) if unicodedata.category(ch) != "Mn")
        raw = re.sub(r"[^a-z0-9\s]", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()

    def _parse_order_info(self, text: str) -> dict:
        product = ""
        quantity = None

        if "marmitex" in text:
            product = "marmitex_individual"
            quantity = self._extract_quantity_for_marmitex(text)
            return {"produto": product, "quantidade": quantity}

        m_people = re.search(r"\b(\d{1,2})\s*pessoas?\b", text)
        if "marmita" in text and m_people:
            people = int(m_people.group(1))
            quantity = people
            if people == 2:
                product = "marmita_2_pessoas"
            elif people == 3:
                product = "marmita_3_pessoas"
            elif people == 4:
                product = "marmita_4_pessoas"
            elif people == 5:
                product = "marmita_5_pessoas"
            else:
                product = "marmita_acima_5_pessoas"
            return {"produto": product, "quantidade": quantity}

        return {"produto": product, "quantidade": quantity}

    def _extract_quantity_for_marmitex(self, text: str) -> int:
        normalized = self._normalize(text)

        # 1) Numero em algarismo imediatamente antes de "marmitex"
        m_digit = re.search(r"\b(\d{1,2})\s*(marmitex|unidades?|u)\b", normalized)
        if m_digit:
            return max(1, int(m_digit.group(1)))

        # 2) Numero por extenso imediatamente antes de "marmitex"
        tokens = normalized.split()
        for idx, token in enumerate(tokens):
            if token == "marmitex" and idx > 0:
                prev = tokens[idx - 1]
                if prev.isdigit():
                    return max(1, int(prev))
                if prev in NUMBER_WORDS:
                    return NUMBER_WORDS[prev]

        # 3) Fallback: primeiro numero (algarismo ou extenso) da frase
        for token in tokens:
            if token.isdigit():
                return max(1, int(token))
            if token in NUMBER_WORDS:
                return NUMBER_WORDS[token]

        return 1

    def _extract_order_items(self, text: str) -> dict:
        normalized = self._normalize(text)
        items: list[dict] = []
        needs_owner = False
        family_spans: list[tuple[int, int]] = []
        incomplete_family_spans: list[tuple[int, int]] = []
        incomplete_family_quantity = 0

        number_pattern = r"\d+|um|uma|dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez"

        # Marmita familiar: aceita tambem "marmitex para duas pessoas",
        # porque clientes usam os termos de forma intercambiavel no WhatsApp.
        for m in re.finditer(
            rf"(?:(?P<qty>{number_pattern})\s+)?marmit(?:a|ex)(?:s)?\s+para\s+(?P<people>{number_pattern})\s+pessoas?",
            normalized,
        ):
            family_spans.append(m.span())
            order_qty = self._to_int(m.group("qty") or "1") or 1
            people = self._to_int(m.group("people")) or 0

            if people > 5:
                needs_owner = True
                continue
            catalog_item = get_order_product_by_people(people, only_available=True)
            if catalog_item is None:
                continue
            unit = float(catalog_item["preco"])
            items.append(
                {
                    "produto": f"marmita para {people} pessoas",
                    "produto_key": f"marmita_{people}_pessoas",
                    "quantidade": order_qty,
                    "valor_unitario": unit,
                    "subtotal": round(order_qty * unit, 2),
                }
            )

        # Marmita sem "para X pessoas" fica pendente para evitar assumir
        # marmitex individual quando o cliente quis marmita familiar.
        for m in re.finditer(
            rf"(?:(?P<qty>{number_pattern})\s+)?marmita(?:s)?(?!\s+para)(?!\s+individuais?)",
            normalized,
        ):
            if self._overlaps_any_span(m.span(), family_spans):
                continue
            incomplete_family_spans.append(m.span())
            incomplete_family_quantity += self._to_int(m.group("qty") or "1") or 1

        # Marmitex individual: "2 marmitex", "duas marmitex".
        # Tambem aceita "marmita individual", mas nao "marmita" generica.
        for m in re.finditer(
            rf"(?:(?P<qty>{number_pattern})\s+)?(?:marmitex(?:s)?|marmita(?:s)?\s+individuais?)",
            normalized,
        ):
            if self._overlaps_any_span(m.span(), family_spans + incomplete_family_spans):
                continue
            qty = self._to_int(m.group("qty") or "1") or 1
            catalog_item = get_order_product("marmitex_individual", only_available=True)
            if catalog_item is None:
                continue
            unit = float(catalog_item["preco"])
            items.append(
                {
                    "produto": "marmitex individual",
                    "produto_key": "marmitex_individual",
                    "quantidade": qty,
                    "valor_unitario": unit,
                    "subtotal": round(qty * unit, 2),
                }
            )

        # Consolida itens iguais (se repetidos na mesma mensagem)
        grouped: dict[tuple[str, float], dict] = {}
        for item in items:
            key = (item["produto"], item["valor_unitario"])
            if key not in grouped:
                grouped[key] = item.copy()
            else:
                grouped[key]["quantidade"] += item["quantidade"]
                grouped[key]["subtotal"] = round(
                    grouped[key]["quantidade"] * grouped[key]["valor_unitario"], 2
                )

        return {
            "items": list(grouped.values()),
            "needs_owner": needs_owner,
            "incomplete_family": bool(incomplete_family_spans),
            "incomplete_family_quantity": incomplete_family_quantity or 1,
        }

    def _overlaps_any_span(self, span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
        start, end = span
        return any(start < other_end and end > other_start for other_start, other_end in spans)

    def _extract_people_count_for_pending_family(self, normalized_text: str) -> int | None:
        for token in normalized_text.split():
            value = self._to_int(token)
            if value:
                return value
        return None

    def _build_partial_items_text(self, items: list[dict]) -> str:
        if not items:
            return ""
        lines = ["Anotei esta parte do pedido:"]
        total = 0.0
        for item in items:
            subtotal = float(item["subtotal"])
            total += subtotal
            subtotal_text = f"R$ {subtotal:.2f}".replace(".", ",")
            qty = int(item["quantidade"])
            produto = self._pluralize_produto(item["produto"], qty)
            lines.append(f"* {qty} {produto}: {subtotal_text}")
        total_text = f"R$ {total:.2f}".replace(".", ",")
        lines.append(f"Parcial: {total_text}")
        return "\n".join(lines)

    def _to_int(self, token: str) -> int | None:
        if not token:
            return None
        t = self._normalize(token)
        if t.isdigit():
            return int(t)
        return NUMBER_WORDS.get(t)

    def _extract_payment(self, text: str) -> str:
        normalized = self._normalize(text)
        if normalized in {"1", "pix"} or "pix" in normalized:
            return "Pix"
        if normalized in {"2", "dinheiro"} or "dinheiro" in normalized:
            return "Dinheiro"
        if normalized in {"3", "cartao"} or "cartao" in normalized:
            return "Cartao"
        return ""

    def _is_delivery_fee_question(self, normalized_text: str) -> bool:
        return (
            "entrega" in normalized_text
            and any(term in normalized_text for term in ["valor", "taxa", "preco", "quanto", "custa", "custo"])
        )

    def _is_price_consultation(self, normalized_text: str) -> bool:
        triggers = [
            "qual o valor",
            "quais os valores",
            "qual os valores",
            "quanto custa",
            "preco",
            "precos",
            "tabela de preco",
            "quero saber o valor",
            "me informa os valores",
            "me passa os precos",
        ]
        return any(t in normalized_text for t in triggers)

    def _is_price_followup(self, normalized_text: str, state) -> bool:
        if state.ultima_intencao != "consultar_valores":
            return False
        if self._is_explicit_order_request(normalized_text):
            return False
        return "marmitex" in normalized_text or "marmita" in normalized_text

    def _build_price_consultation_response(self, normalized_text: str, in_order: bool) -> str:
        lines: list[str] = []
        has_specific = False

        if "marmitex" in normalized_text:
            product = get_order_product("marmitex_individual", only_available=True)
            if product is not None:
                lines.append(f"A marmitex individual custa {format_brl(product['preco'])}.")
            else:
                lines.append("No momento a marmitex individual nao esta disponivel.")
            has_specific = True

        for people in [2, 3, 4, 5]:
            words = {str(people), self._number_word(people)}
            if any(
                (f"marmita para {w} pessoas" in normalized_text) or (f"marmita para {w} pessoa" in normalized_text)
                for w in words
            ):
                product = get_order_product_by_people(people, only_available=True)
                if product is not None:
                    lines.append(f"A marmita para {people} pessoas custa {format_brl(product['preco'])}.")
                else:
                    lines.append(f"No momento a marmita para {people} pessoas nao esta disponivel.")
                has_specific = True

        if not has_specific:
            available_products = list_order_products(only_available=True)
            if available_products:
                lines = ["Nossos valores sao:\n"]
                for product in available_products:
                    lines.append(f"* {product['nome']}: {format_brl(product['preco'])}")
                lines.append("\nPara pedidos acima de 5 pessoas, preciso consultar a proprietaria.")
            else:
                lines = ["No momento nao ha opcoes de pedido disponiveis no catalogo."]

        if in_order:
            lines.append("\nQuer continuar seu pedido? 😊")
        else:
            lines.append("\nSe quiser, posso continuar seu pedido 😊")

        return "\n".join(lines)

    def _number_word(self, num: int) -> str:
        mapping = {2: "duas", 3: "tres", 4: "quatro", 5: "cinco"}
        return mapping.get(num, str(num))

    def _is_local_pickup(self, normalized_text: str) -> bool:
        pickup_terms = [
            "vou buscar",
            "vou retirar",
            "vou pegar no local",
            "pego no local",
            "retiro no local",
            "vou passar ai",
            "passo buscar",
            "busco ai",
            "voubpegar no local",
        ]
        compact = normalized_text.replace(" ", "")
        if "voubpegarnolocal" in compact:
            return True
        return any(term in normalized_text for term in pickup_terms)

    def _is_delivery_choice(self, normalized_text: str) -> bool:
        return normalized_text in {"1", "entrega", "quero entrega", "entregar"}

    def _is_pickup_choice(self, normalized_text: str) -> bool:
        if normalized_text == "2":
            return True
        return self._is_local_pickup(normalized_text) or normalized_text in {"retirada", "retirar"}

    def _looks_like_address(self, text: str) -> bool:
        return any(k in text for k in ["rua", "av", "avenida", "travessa", "bairro", "numero", "nº", "cep"])

    def _product_selection_prompt(self) -> str:
        choices = get_order_product_choices()
        if not choices:
            return (
                "No momento nao ha produtos de pedido disponiveis no catalogo. "
                "Pode falar com a atendente para ajustar a disponibilidade."
            )

        lines = ["Voce deseja:"]
        for item in choices:
            lines.append(f"{item['choice']} - {item['nome']}")
        lines.append("")
        lines.append('Ou, se preferir, me diga direto a quantidade. Exemplo: "quero 3 marmitex".')
        return "\n".join(lines)

    def _catalog_unavailable_response(self, telefone: str, product_name: str) -> dict:
        response = (
            f"No momento {product_name.lower()} nao esta disponivel. "
            "Se quiser, posso te mostrar as opcoes que estao disponiveis agora."
        )
        return {
            "state": asdict(get_or_create_state(telefone)),
            "pricing": {
                "can_calculate": False,
                "needs_owner": False,
                "unit_price": 0.0,
                "total_price": 0.0,
            },
            "next_question": self._product_selection_prompt(),
            "response": f"{response}\n\n{self._product_selection_prompt()}",
        }

    def _calculate_price(self, produto: str, quantidade: int) -> dict:
        if not produto:
            return {"can_calculate": False, "needs_owner": False, "unit_price": 0.0, "total_price": 0.0}

        if produto == "marmita_acima_5_pessoas":
            return {"can_calculate": False, "needs_owner": True, "unit_price": 0.0, "total_price": 0.0}

        if produto == "marmitex_individual":
            qty = max(1, int(quantidade or 1))
            catalog_item = get_order_product(produto, only_available=True)
            if catalog_item is None:
                return {"can_calculate": False, "needs_owner": False, "unit_price": 0.0, "total_price": 0.0}
            unit = float(catalog_item["preco"])
            return {
                "can_calculate": True,
                "needs_owner": False,
                "unit_price": unit,
                "total_price": round(unit * qty, 2),
            }

        catalog_item = get_order_product(produto, only_available=True)
        if catalog_item is not None:
            value = float(catalog_item["preco"])
            return {
                "can_calculate": True,
                "needs_owner": False,
                "unit_price": value,
                "total_price": value,
            }

        return {"can_calculate": False, "needs_owner": False, "unit_price": 0.0, "total_price": 0.0}

    def _should_confirm_item(self, state, text: str) -> bool:
        if state.produto != "marmitex_individual":
            return False
        if state.endereco or state.forma_pagamento:
            return False
        return any(k in text for k in ["total", "valor", "quanto", "custa", "custar"])

    def _is_total_question(self, text: str) -> bool:
        return "valor total" in text or ("total" in text and "pedido" in text) or "qual o total" in text

    def _looks_like_receipt(self, text: str) -> bool:
        return any(
            k in text
            for k in ["comprovante", "enviei", "enviado", "segue", "paguei", "pagamento feito", "anexo"]
        )

    def _awaiting_field(self, state, pricing: dict) -> str:
        if not state.produto:
            return "produto"
        if not state.quantidade:
            return "quantidade"
        if pricing.get("needs_owner"):
            return "consulta_proprietaria"
        if not state.tipo_entrega:
            return "tipo_entrega"
        if state.tipo_entrega != "retirada" and not state.endereco:
            return "endereco"
        if not state.forma_pagamento:
            return "forma_pagamento"
        if state.forma_pagamento == "Pix":
            return "comprovante"
        return "confirmacao"

    def _next_question(self, state, pricing: dict) -> str:
        waiting = self._awaiting_field(state, pricing)
        if waiting == "produto":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_PRODUTO)
            return self._product_selection_prompt()
        if waiting == "quantidade":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_QUANTIDADE)
            return "Qual a quantidade desejada?"
        if waiting == "consulta_proprietaria":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.ENCAMINHAR_ATENDENTE)
            return (
                "Para pedidos acima de 5 pessoas, preciso consultar a proprietaria "
                "do estabelecimento para confirmar o valor certinho."
            )
        if waiting == "tipo_entrega":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
            return "Voce prefere:\n1 - Entrega\n2 - Retirada no local\n\nEntregas e retiradas acontecem das 11h às 13h."
        if waiting == "endereco":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_ENDERECO)
            return "Pode me informar o endereco de entrega, por favor?"
        if waiting == "forma_pagamento":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO)
            return "Qual sera a forma de pagamento? Pix, dinheiro ou cartao?"
        if waiting == "comprovante":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_COMPROVANTE)
            return "Certo 😊 Pode enviar o comprovante por aqui assim que fizer o pagamento."

        update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_CONFIRMACAO)
        return "Posso seguir com esse pedido? Se estiver tudo certo, me confirme por favor."

    def _build_response(self, state, pricing: dict, next_question: str) -> str:
        if pricing.get("needs_owner"):
            return next_question

        if state.itens_pedido and pricing.get("can_calculate"):
            if state.endereco and not state.forma_pagamento:
                return "Perfeito 😊 Endereco anotado. Qual sera a forma de pagamento? Pix, dinheiro ou cartao?"
            if state.forma_pagamento and state.forma_pagamento != "Pix":
                return self._build_order_summary(state)
            if state.forma_pagamento == "Pix":
                return f"Certo 😊 Pode enviar o comprovante por aqui assim que fizer o pagamento."
            return next_question

        if (
            state.produto
            and state.quantidade
            and state.endereco
            and state.forma_pagamento
            and pricing.get("can_calculate")
            and state.forma_pagamento != "Pix"
        ):
            return self._build_order_summary(state)

        if state.produto and pricing.get("can_calculate"):
            total = f"R$ {pricing['total_price']:.2f}".replace(".", ",")
            if not state.tipo_entrega:
                produto = self._human_product_name(state.produto, state.quantidade)
                return (
                    f"Perfeito 😊 {produto} ficam em {total}.\n\n"
                    "Voce prefere:\n1 - Entrega\n2 - Retirada no local\n\n"
                    "Entregas e retiradas acontecem das 11h às 13h."
                )
            if state.tipo_entrega != "retirada" and not state.endereco:
                produto = self._human_product_name(state.produto, state.quantidade)
                return (
                    f"Perfeito 😊 {produto} ficam em {total}. "
                    "Pode me informar o endereco de entrega, por favor?"
                )
            return f"Perfeito! Valor parcial do pedido: {total}. {next_question}"

        return next_question

    def _human_product_name(self, produto: str, quantidade: int) -> str:
        if produto == "marmitex_individual":
            if int(quantidade or 0) > 1:
                return f"{quantidade} marmitex individuais"
            return f"{quantidade} marmitex individual"
        if produto == "marmita_2_pessoas":
            return "marmita para 2 pessoas"
        if produto == "marmita_3_pessoas":
            return "marmita para 3 pessoas"
        if produto == "marmita_4_pessoas":
            return "marmita para 4 pessoas"
        if produto == "marmita_5_pessoas":
            return "marmita para 5 pessoas"
        return "pedido"

    def _build_order_summary(self, state) -> str:
        total = f"R$ {state.valor_total:.2f}".replace(".", ",")
        if state.itens_pedido:
            item_lines = []
            for item in state.itens_pedido:
                subtotal = f"R$ {float(item['subtotal']):.2f}".replace(".", ",")
                qty = int(item["quantidade"])
                produto = self._pluralize_produto(item["produto"], qty)
                item_lines.append(f"- {qty} {produto}: {subtotal}")
            itens = "\n".join(item_lines)
            return (
                "Resumo do seu pedido:\n"
                f"{itens}\n"
                f"- Entrega: {state.endereco}\n"
                f"- Forma de pagamento: {state.forma_pagamento}\n"
                f"- Total: {total}\n"
                "Posso seguir com esse pedido? Se estiver tudo certo, me confirme por favor."
            )

        produto_legivel = self._human_product_name(state.produto, state.quantidade)
        return (
            "Resumo do seu pedido:\n"
            f"- Produto: {produto_legivel}\n"
            f"- Endereco: {state.endereco}\n"
            f"- Forma de pagamento: {state.forma_pagamento}\n"
            f"- Total: {total}\n"
            "Posso seguir com esse pedido? Se estiver tudo certo, me confirme por favor."
        )

    def _build_payment_proof_received_response(self, state) -> str:
        total = f"R$ {state.valor_total:.2f}".replace(".", ",")
        lines = [
            "Comprovante recebido 😊",
            "",
            "Vou deixar o pagamento em conferencia. Por seguranca, ainda nao confirmo o pagamento automaticamente por aqui.",
        ]
        if state.itens_pedido:
            item_lines = []
            for item in state.itens_pedido:
                subtotal = f"R$ {float(item['subtotal']):.2f}".replace(".", ",")
                qty = int(item["quantidade"])
                produto = self._pluralize_produto(item["produto"], qty)
                item_lines.append(f"* {qty} {produto}: {subtotal}")
            lines.extend(["", "Resumo do pedido:", *item_lines, f"Total: {total}"])
        elif state.produto:
            produto_legivel = self._human_product_name(state.produto, state.quantidade)
            lines.extend(["", "Resumo do pedido:", f"* {produto_legivel}", f"Total: {total}"])
        lines.append("")
        lines.append("A equipe precisa validar o comprovante antes de confirmar o pedido.")
        return "\n".join(lines)

    def _build_items_summary_response(self, items: list[dict], total: float, ask_address: bool) -> str:
        lines = ["Perfeito 😊 Seu pedido ficou assim:\n"]
        for item in items:
            subtotal = f"R$ {float(item['subtotal']):.2f}".replace(".", ",")
            qty = int(item["quantidade"])
            produto = item["produto"]
            produto_label = self._pluralize_produto(produto, qty)
            if qty == 1:
                lines.append(f"* 1 {produto}: {subtotal}")
            else:
                lines.append(f"* {qty} {produto_label}: {subtotal}")
        total_str = f"R$ {float(total):.2f}".replace(".", ",")
        lines.append(f"\nTotal: {total_str}")
        if ask_address:
            lines.append("\nVoce prefere:\n1 - Entrega\n2 - Retirada no local")
            lines.append("\nEntregas e retiradas acontecem das 11h às 13h.")
        return "\n".join(lines)

    def _pluralize_produto(self, produto: str, quantidade: int) -> str:
        if quantidade <= 1:
            return produto
        if produto == "marmitex individual":
            return "marmitex individuais"
        return produto


def run_order_agent_quantity_tests() -> dict:
    from .conversation_state import reset_state

    agent = OrderAgent()
    cases = [
        ("5510001", "Eu quero três marmitex"),
        ("5510002", "Quero 3 marmitex"),
        ("5510003", "Eu pedi três marmitex"),
        ("5510004", "Quero duas marmitex"),
    ]
    out = {}
    for phone, msg in cases:
        reset_state(phone)
        result = agent.process_message(phone, msg)
        state = result["state"]
        out[msg] = {
            "produto": state["produto"],
            "quantidade": state["quantidade"],
            "valor_unitario": state["valor_unitario"],
            "valor_total": state["valor_total"],
            "response": result["response"],
        }
    return out

import re
import unicodedata
from dataclasses import asdict

from .conversation_state import AtendimentoStatus, get_or_create_state, reset_state, update_state
from .payment_proof_agent import PaymentProofAgent

PRICE_TABLE = {
    "marmitex_individual": 21.00,
    "marmita_2_pessoas": 65.00,
    "marmita_3_pessoas": 85.00,
    "marmita_4_pessoas": 105.00,
    "marmita_5_pessoas": 125.00,
}

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
        file_name: str = "",
        file_mimetype: str = "",
    ) -> dict:
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
            if self._is_delivery_fee_question(normalized):
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": "Voce prefere:\n1 - Entrega\n2 - Retirada no local",
                    "response": (
                        "A taxa de entrega depende do endereco. "
                        "Se voce escolher entrega, me envie o endereco que confirmamos certinho.\n\n"
                        "Voce prefere:\n1 - Entrega\n2 - Retirada no local"
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
                "response": "Voce prefere:\n1 - Entrega\n2 - Retirada no local",
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
            waiting_question = "Voce prefere:\n1 - Entrega\n2 - Retirada no local"
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

        if items_data["items"]:
            total_price = round(sum(item["subtotal"] for item in items_data["items"]), 2)
            first = items_data["items"][0]
            update_state(
                telefone,
                ultima_intencao="fazer_pedido",
                status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA,
                itens_pedido=items_data["items"],
                produto=first["produto_key"],
                quantidade=first["quantidade"],
                valor_unitario=first["valor_unitario"],
                valor_total=total_price,
                aguardando_resposta="tipo_entrega",
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
                "next_question": "Pode me informar o endereco de entrega, por favor?",
                "response": response,
            }

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
                    "Assim que for validado, o pedido pode ser confirmado pela equipe."
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

    def _wants_to_order(self, text: str) -> bool:
        return any(k in text for k in ["pedido", "pedir", "quero", "comprar", "marmita", "marmitex"])

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
            price_map = {
                2: PRICE_TABLE["marmita_2_pessoas"],
                3: PRICE_TABLE["marmita_3_pessoas"],
                4: PRICE_TABLE["marmita_4_pessoas"],
                5: PRICE_TABLE["marmita_5_pessoas"],
            }
            if people not in price_map:
                continue
            unit = price_map[people]
            items.append(
                {
                    "produto": f"marmita para {people} pessoas",
                    "produto_key": f"marmita_{people}_pessoas",
                    "quantidade": order_qty,
                    "valor_unitario": unit,
                    "subtotal": round(order_qty * unit, 2),
                }
            )

        # Marmitex/marmita individual: "2 marmitex", "duas marmitas".
        # Ignora trechos ja capturados como marmita familiar.
        for m in re.finditer(
            rf"(?:(?P<qty>{number_pattern})\s+)?marmit(?:ex|a)(?:s)?(?:\s+individuais?)?",
            normalized,
        ):
            if self._overlaps_any_span(m.span(), family_spans):
                continue
            qty = self._to_int(m.group("qty") or "1") or 1
            unit = PRICE_TABLE["marmitex_individual"]
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

        return {"items": list(grouped.values()), "needs_owner": needs_owner}

    def _overlaps_any_span(self, span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
        start, end = span
        return any(start < other_end and end > other_start for other_start, other_end in spans)

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
            lines.append("A marmitex individual custa R$ 21,00.")
            has_specific = True

        for people, value in [(2, "R$ 65,00"), (3, "R$ 85,00"), (4, "R$ 105,00"), (5, "R$ 125,00")]:
            words = {str(people), self._number_word(people)}
            if any(
                (f"marmita para {w} pessoas" in normalized_text) or (f"marmita para {w} pessoa" in normalized_text)
                for w in words
            ):
                lines.append(f"A marmita para {people} pessoas custa {value}.")
                has_specific = True

        if not has_specific:
            lines = [
                "Nossos valores sao:\n",
                "* Marmitex individual: R$ 21,00",
                "* Marmita para 2 pessoas: R$ 65,00",
                "* Marmita para 3 pessoas: R$ 85,00",
                "* Marmita para 4 pessoas: R$ 105,00",
                "* Marmita para 5 pessoas: R$ 125,00",
                "\nPara pedidos acima de 5 pessoas, preciso consultar a proprietaria.",
            ]

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

    def _calculate_price(self, produto: str, quantidade: int) -> dict:
        if not produto:
            return {"can_calculate": False, "needs_owner": False, "unit_price": 0.0, "total_price": 0.0}

        if produto == "marmita_acima_5_pessoas":
            return {"can_calculate": False, "needs_owner": True, "unit_price": 0.0, "total_price": 0.0}

        if produto == "marmitex_individual":
            qty = max(1, int(quantidade or 1))
            unit = PRICE_TABLE["marmitex_individual"]
            return {
                "can_calculate": True,
                "needs_owner": False,
                "unit_price": unit,
                "total_price": round(unit * qty, 2),
            }

        if produto in PRICE_TABLE:
            value = PRICE_TABLE[produto]
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
            return "Qual produto voce deseja? Marmitex individual ou marmita para quantas pessoas?"
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
            return "Voce prefere:\n1 - Entrega\n2 - Retirada no local"
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
                    "Voce prefere:\n1 - Entrega\n2 - Retirada no local"
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

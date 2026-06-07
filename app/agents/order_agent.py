import logging
import re
import unicodedata
from dataclasses import asdict
from decimal import Decimal

from django.test.testcases import DatabaseOperationForbidden

from app.business_config import (
    current_weekday_key,
    delivery_hours_summary,
    format_day_display,
    format_time_br,
    get_active_business_settings,
    owner_consultation_message,
    owner_consultation_threshold,
    pickup_hours_summary,
)
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

logger = logging.getLogger(__name__)


class OrderAgent:
    """Controla montagem de pedido durante a conversa."""

    def __init__(self) -> None:
        self.payment_proof_agent = PaymentProofAgent()

    def persist_order_snapshot(self, telefone: str, mark_cancelled: bool = False) -> None:
        try:
            from django.db import transaction

            from app.models import Cliente, Conversa, ItemPedido, Pedido, Produto

            state = get_or_create_state(telefone)
            cliente, _ = Cliente.objects.get_or_create(telefone=telefone)
            customer_name = self._get_customer_name(telefone)
            if customer_name and cliente.nome != customer_name:
                cliente.nome = customer_name
                cliente.save(update_fields=["nome", "atualizado_em"])

            conversa = (
                Conversa.objects.filter(cliente=cliente)
                .exclude(status=Conversa.Status.FINALIZADA)
                .order_by("-atualizado_em")
                .first()
            )
            if conversa is None:
                conversa = Conversa.objects.create(cliente=cliente, status=Conversa.Status.IA)

            pedido = (
                Pedido.objects.filter(conversa=conversa)
                .exclude(status__in=[Pedido.Status.ENTREGUE, Pedido.Status.CANCELADO])
                .order_by("-criado_em")
                .first()
            )

            if mark_cancelled:
                if pedido is not None:
                    pedido.status = Pedido.Status.CANCELADO
                    pedido.save(update_fields=["status", "atualizado_em"])
                return

            has_order_payload = bool(
                state.itens_pedido or state.produto or state.quantidade or state.valor_total or state.forma_pagamento
            )
            if not has_order_payload:
                return

            if pedido is None:
                pedido = Pedido.objects.create(cliente=cliente, conversa=conversa, status=Pedido.Status.RASCUNHO)

            computed_status = self._db_status_from_state(state)
            pedido.forma_pagamento = self._db_payment_value(state.forma_pagamento)
            pedido.endereco_entrega = state.endereco if state.tipo_entrega == "entrega" else ""
            pedido.observacoes = self._build_db_order_notes(state)
            pedido.subtotal = Decimal(str(state.valor_total or 0.0))
            pedido.total = Decimal(str(state.valor_total or 0.0))
            pedido.taxa_entrega = Decimal("0.00")
            pedido.status = self._preserve_advanced_db_status(pedido.status, computed_status)

            with transaction.atomic():
                pedido.save(
                    update_fields=[
                        "forma_pagamento",
                        "endereco_entrega",
                        "observacoes",
                        "subtotal",
                        "total",
                        "taxa_entrega",
                        "status",
                        "atualizado_em",
                    ]
                )
                ItemPedido.objects.filter(pedido=pedido).delete()
                for item in self._items_for_persistence(state):
                    produto = None
                    produto_id = item.get("produto_id")
                    if produto_id:
                        produto = Produto.objects.filter(pk=produto_id).first()
                    if produto is None:
                        catalog_item = get_order_product(item["produto_key"], only_available=False)
                        if catalog_item and catalog_item.get("produto"):
                            produto = catalog_item["produto"]
                    if produto is None:
                        continue
                    quantidade = max(1, int(item["quantidade"]))
                    preco_unitario = Decimal(str(item["valor_unitario"]))
                    subtotal = Decimal(str(item["subtotal"]))
                    ItemPedido.objects.create(
                        pedido=pedido,
                        produto=produto,
                        quantidade=quantidade,
                        preco_unitario=preco_unitario,
                        subtotal=subtotal,
                    )
        except DatabaseOperationForbidden:
            logger.debug(
                "Persistência do pedido ignorada por ambiente de teste sem acesso ao banco telefone=%s",
                telefone,
            )
        except Exception:
            logger.exception("Falha ao persistir snapshot do pedido telefone=%s", telefone)

    def _items_for_persistence(self, state) -> list[dict]:
        if state.itens_pedido:
            return list(state.itens_pedido)
        if state.produto and state.quantidade and state.valor_total:
            item = self._make_item_from_key(state.produto, int(state.quantidade or 1))
            return [item] if item else []
        return []

    def _db_payment_value(self, payment_label: str) -> str:
        normalized = self._normalize(payment_label)
        if normalized == "pix":
            return "pix"
        if normalized == "dinheiro":
            return "dinheiro"
        if normalized == "cartao":
            return "cartao_entrega"
        return ""

    def _db_status_from_state(self, state) -> str:
        if state.status_atendimento in {
            AtendimentoStatus.AGUARDANDO_COMPROVANTE,
            AtendimentoStatus.AGUARDANDO_CONFERENCIA_PAGAMENTO,
        }:
            return "aguardando_pagamento"
        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFIRMACAO:
            return "aguardando_confirmacao"
        if state.forma_pagamento == "Pix":
            return "aguardando_pagamento"
        if state.forma_pagamento in {"Dinheiro", "Cartão"}:
            return "aguardando_confirmacao"
        return "rascunho"

    def _preserve_advanced_db_status(self, current_status: str, computed_status: str) -> str:
        if current_status in {"em_preparo", "saiu_para_entrega", "entregue"}:
            return current_status
        return computed_status

    def _build_db_order_notes(self, state) -> str:
        notes: list[str] = []
        customer_name = self._get_customer_name(state.telefone)
        if state.tipo_entrega == "retirada":
            notes.append("Forma de recebimento: retirada no local")
        elif state.tipo_entrega == "entrega":
            notes.append("Forma de recebimento: entrega")
        if customer_name:
            notes.append(f"Nome: {customer_name}")
        for item in state.itens_pedido or []:
            observation = (item.get("observacao") or "").strip()
            if observation:
                notes.append(f"Observação: {observation}")
        return "\n".join(notes)

    def _business_settings(self):
        return get_active_business_settings()

    def _owner_threshold(self) -> int:
        return owner_consultation_threshold(self._business_settings())

    def _owner_consultation_message(self) -> str:
        return owner_consultation_message(self._business_settings())

    def _family_people_prompt(self) -> str:
        threshold = min(self._owner_threshold(), 5)
        if threshold < 2:
            return self._owner_consultation_message()
        options = ", ".join(str(item) for item in range(2, threshold + 1))
        return f"Essa marmita é para quantas pessoas? Temos opções para {options} pessoas."

    def _delivery_and_pickup_hours_text(self) -> str:
        business = self._business_settings()
        day_key = current_weekday_key()
        day_label = format_day_display(day_key)
        schedule = business.schedule_for_day(day_key)
        if not schedule or schedule.fechado:
            return f"Hoje, {day_label}, não temos atendimento para entregas e retiradas."

        delivery_text = ""
        pickup_text = ""
        if business.aceita_entrega and schedule.abre_entregas and schedule.fecha_entregas:
            delivery_text = f"das {format_time_br(schedule.abre_entregas)} às {format_time_br(schedule.fecha_entregas)}"
        if business.aceita_retirada_local and schedule.abre_retiradas and schedule.fecha_retiradas:
            pickup_text = f"das {format_time_br(schedule.abre_retiradas)} às {format_time_br(schedule.fecha_retiradas)}"

        if delivery_text and pickup_text:
            if delivery_text == pickup_text:
                return f"Hoje, {day_label}, entregas e retiradas acontecem {delivery_text}."
            return (
                f"Hoje, {day_label}, entregas acontecem {delivery_text}. "
                f"Retiradas acontecem {pickup_text}."
            )
        if delivery_text:
            return f"Hoje, {day_label}, entregas acontecem {delivery_text}."
        if pickup_text:
            return f"Hoje, {day_label}, retiradas acontecem {pickup_text}."
        return f"Hoje, {day_label}, entregas e retiradas estão indisponíveis."

    def _list_available_complements(self) -> list[dict]:
        try:
            from app.models import Produto

            queryset = (
                Produto.objects.filter(
                    categoria__in=[
                        Produto.Categoria.BEBIDA,
                        Produto.Categoria.ADICIONAL,
                        Produto.Categoria.SOBREMESA,
                    ],
                    disponivel=True,
                )
                .order_by("categoria", "nome")
            )
            options: list[dict] = []
            for index, produto in enumerate(queryset, start=1):
                if produto.preco is None or produto.preco <= 0:
                    continue
                options.append(
                    {
                        "choice": str(index),
                        "produto": (produto.nome or "").strip().lower(),
                        "produto_key": f"complemento_{produto.id}",
                        "produto_id": produto.id,
                        "valor_unitario": float(produto.preco),
                        "categoria": produto.categoria,
                    }
                )
            return options
        except DatabaseOperationForbidden:
            return []
        except Exception:
            logger.exception("Falha ao listar complementos disponíveis.")
            return []

    def _complement_skip_choice(self, options: list[dict]) -> str:
        return str(len(options) + 1)

    def _complement_prompt(self) -> str:
        options = self._list_available_complements()
        if not options:
            return self._delivery_mode_prompt()

        lines = ["Deseja adicionar alguma bebida ou complemento?", ""]
        for option in options:
            lines.append(
                f"{option['choice']} - {option['produto'].capitalize()}: {format_brl(option['valor_unitario'])}"
            )
        lines.append(f"{self._complement_skip_choice(options)} - Não, obrigado")
        return "\n".join(lines)

    def _more_complements_prompt(self) -> str:
        return "Deseja adicionar mais algum item?\n\n1 - Sim\n2 - Não, seguir pedido"

    def _is_negative_complement_answer(self, normalized_text: str, skip_choice: str = "") -> bool:
        if skip_choice and normalized_text == skip_choice:
            return True
        return any(
            marker in normalized_text
            for marker in [
                "nao",
                "nao quero",
                "nao obrigado",
                "nao obrigada",
                "sem bebida",
                "sem sobremesa",
                "sem adicional",
                "sem complemento",
                "sem mais",
                "pode seguir",
                "seguir pedido",
                "seguir",
                "sem nada",
            ]
        )

    def _is_positive_more_complements_answer(self, normalized_text: str) -> bool:
        return normalized_text in {
            "1",
            "sim",
            "quero",
            "quero sim",
            "mais um",
            "mais uma",
            "adiciona",
            "adicionar",
        }

    def _find_pending_complement(self, state) -> dict | None:
        for item in state.itens_pendentes or []:
            if item.get("produto_key", "").startswith("complemento_"):
                return item
        return None

    def _extract_complement_choice(self, normalized_text: str, options: list[dict]) -> dict | None:
        if not normalized_text:
            return None

        selected_choice = next((item for item in options if item["choice"] == normalized_text), None)
        if selected_choice is not None:
            return selected_choice

        full_name_matches = [
            option
            for option in options
            if self._normalize(option["produto"]) in normalized_text
        ]
        if full_name_matches:
            return max(full_name_matches, key=lambda item: len(item["produto"]))

        ignored_tokens = {"de", "do", "da", "das", "dos", "e", "com", "sem", "para", "lata", "mineral", "dia", "adicional"}
        token_matches: list[tuple[int, dict]] = []
        for option in options:
            significant_tokens = [
                token
                for token in self._normalize(option["produto"]).split()
                if len(token) >= 3 and token not in ignored_tokens
            ]
            for token in significant_tokens:
                if token in normalized_text:
                    token_matches.append((len(token), option))
                    break
        if token_matches:
            token_matches.sort(key=lambda item: item[0], reverse=True)
            return token_matches[0][1]
        return None

    def _prompt_complement_quantity(self, option: dict) -> str:
        return f"Qual quantidade de {option['produto']} você deseja adicionar?"

    def _merge_item_lists(self, current_items: list[dict], extra_item: dict) -> list[dict]:
        merged = [item.copy() for item in current_items]
        for item in merged:
            if item.get("produto_id") and item.get("produto_id") == extra_item.get("produto_id"):
                item["quantidade"] = int(item.get("quantidade") or 0) + int(extra_item["quantidade"])
                item["subtotal"] = round(item["quantidade"] * float(item["valor_unitario"]), 2)
                return merged
            if item.get("produto_key") == extra_item.get("produto_key"):
                item["quantidade"] = int(item.get("quantidade") or 0) + int(extra_item["quantidade"])
                item["subtotal"] = round(item["quantidade"] * float(item["valor_unitario"]), 2)
                return merged
        merged.append(extra_item)
        return merged

    def _build_complement_item(self, option: dict, quantidade: int) -> dict:
        qty = max(1, int(quantidade or 1))
        return {
            "produto": option["produto"],
            "produto_key": option["produto_key"],
            "produto_id": option.get("produto_id"),
            "quantidade": qty,
            "valor_unitario": float(option["valor_unitario"]),
            "subtotal": round(qty * float(option["valor_unitario"]), 2),
        }

    def _should_add_complement_immediately(
        self,
        message: str,
        quantidade: int | None,
        selected_option: dict | None = None,
    ) -> bool:
        if not quantidade:
            return False
        normalized = self._normalize(message)
        if selected_option is not None and normalized == (selected_option.get("choice") or ""):
            return False
        return True

    def _finish_complement_stage(self, telefone: str) -> dict:
        update_state(telefone, aguardando_resposta="tipo_entrega", itens_pendentes=[])
        refreshed = get_or_create_state(telefone)
        pricing = {
            "can_calculate": bool(refreshed.valor_total),
            "needs_owner": False,
            "unit_price": refreshed.valor_unitario,
            "total_price": refreshed.valor_total,
        }
        next_question = self._next_question(refreshed, pricing)
        current_state = get_or_create_state(telefone)
        update_state(telefone, aguardando_resposta=self._awaiting_field(current_state, pricing))
        current_state = get_or_create_state(telefone)
        return {
            "state": asdict(current_state),
            "pricing": pricing,
            "next_question": next_question,
            "response": next_question,
        }

    def _add_complement_to_order(self, telefone: str, option: dict, quantidade: int) -> dict:
        state = get_or_create_state(telefone)
        updated_items = self._merge_item_lists(
            state.itens_pedido or [],
            self._build_complement_item(option, quantidade),
        )
        total_price = round(sum(float(item["subtotal"]) for item in updated_items), 2)
        update_state(
            telefone,
            itens_pedido=updated_items,
            valor_total=total_price,
            valor_unitario=float(updated_items[0]["valor_unitario"]) if updated_items else 0.0,
            aguardando_resposta="mais_complementos",
            itens_pendentes=[],
        )
        refreshed = get_or_create_state(telefone)
        response = self._build_items_summary_response(
            items=refreshed.itens_pedido,
            total=refreshed.valor_total,
            ask_address=False,
            title="Perfeito 😊 Atualizei seu pedido:",
        )
        response = f"{response}\n\n{self._more_complements_prompt()}"
        return {
            "state": asdict(refreshed),
            "pricing": {
                "can_calculate": True,
                "needs_owner": False,
                "unit_price": refreshed.valor_unitario,
                "total_price": refreshed.valor_total,
            },
            "next_question": self._more_complements_prompt(),
            "response": response,
        }

    def _delivery_mode_prompt(self) -> str:
        business = self._business_settings()
        if business.aceita_entrega and business.aceita_retirada_local:
            return (
                "Você prefere:\n\n1 - Entrega\n2 - Retirada no local\n\n"
                f"{self._delivery_and_pickup_hours_text()}"
            )
        if business.aceita_entrega:
            return (
                "No momento trabalhamos apenas com entrega.\n\n"
                "1 - Entrega\n\n"
                f"{self._delivery_and_pickup_hours_text()}"
            )
        if business.aceita_retirada_local:
            return (
                "No momento trabalhamos apenas com retirada no local.\n\n"
                "2 - Retirada no local\n\n"
                f"{self._delivery_and_pickup_hours_text()}"
            )
        return "No momento entrega e retirada estão indisponíveis. Fale com a atendente para seguir com o pedido."

    def _payment_options_prompt(self) -> str:
        return "Qual será a forma de pagamento?\n1 - Pix\n2 - Dinheiro\n3 - Cartão"

    def _pickup_confirmation_text(self) -> str:
        business = self._business_settings()
        location = business.endereco_retirada.strip()
        if location:
            return f"Perfeito 😊 Vou marcar como retirada no local em {location}."
        return "Perfeito 😊 Vou marcar como retirada no local."

    def _customer_name_prompt(self) -> str:
        return "Qual nome devo colocar no pedido?"

    def _invalid_customer_name_prompt(self) -> str:
        return "Pode me informar o nome para identificar o pedido, por favor?"

    def _delivery_address_prompt(self) -> str:
        return "Por favor, informe o endereço completo para entrega."

    def _get_customer_name(self, telefone: str) -> str:
        try:
            from app.models import Cliente

            cliente = Cliente.objects.filter(telefone=telefone).only("nome").first()
            return (cliente.nome or "").strip() if cliente else ""
        except Exception:
            return ""

    def _set_customer_name(self, telefone: str, name: str) -> str:
        cleaned = self._extract_customer_name(name)
        if not cleaned:
            return ""
        try:
            from app.models import Cliente

            cliente, _ = Cliente.objects.get_or_create(telefone=telefone)
            if cliente.nome != cleaned:
                cliente.nome = cleaned
                cliente.save(update_fields=["nome"])
        except Exception:
            pass
        return cleaned

    def _extract_customer_name(self, text: str) -> str:
        original = re.sub(
            r"^\s*(meu nome e|meu nome eh|meu nome é|nome|pode colocar|coloca|sou)\s+",
            "",
            (text or "").strip(),
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", original).strip(" .,:;-")
        if not cleaned:
            return ""
        if not re.search(r"[A-Za-zÀ-ÿ]", cleaned):
            return ""
        if len(cleaned) > 80:
            cleaned = cleaned[:80].rstrip()
        return " ".join(part.capitalize() for part in cleaned.split())

    def _payment_summary_response(self, state, customer_name: str) -> str:
        total = format_brl(state.valor_total or 0)
        lines = [f"Obrigado, {customer_name} 😊", "", "Resumo do pedido:", ""]
        lines.extend(self._order_item_lines(state))
        lines.append("")
        lines.append(f"Forma de recebimento: {self._receiving_label(state)}")
        if state.tipo_entrega == "entrega" and state.endereco:
            lines.append(f"Endereço: {state.endereco}")
        lines.append(f"Nome: {customer_name}")
        lines.append(f"Total: {total}")
        lines.extend(["", "Qual será a forma de pagamento?", "", "1 - Pix", "2 - Dinheiro", "3 - Cartão"])
        return "\n".join(lines)

    def _order_item_lines(self, state) -> list[str]:
        if state.itens_pedido:
            item_lines = []
            for item in state.itens_pedido:
                subtotal = f"R$ {float(item['subtotal']):.2f}".replace(".", ",")
                qty = int(item["quantidade"])
                produto = self._pluralize_produto(item["produto"], qty)
                item_lines.append(f"* {qty} {produto}: {subtotal}")
                observation = (item.get("observacao") or "").strip()
                if observation:
                    item_lines.append(f"* Observação: {observation}")
            return item_lines

        total = format_brl(state.valor_total or 0)
        return [f"* {self._human_product_name(state.produto, state.quantidade)}: {total}"]

    def _receiving_label(self, state) -> str:
        if state.tipo_entrega == "retirada":
            return "retirada no local"
        if state.tipo_entrega == "entrega":
            return "entrega"
        return "não definido"

    def _extract_order_observation(self, text: str) -> str:
        original = (text or "").strip()
        if not original:
            return ""

        patterns = [
            r"\b(acrescent(?:ar|a|o)?\b.*)$",
            r"\b(adicion(?:ar|a|e)?\b.*)$",
            r"\b(colocar mais\b.*)$",
            r"\b(extra\b.*)$",
            r"\b(adicional\b.*)$",
            r"\b(mais\s+\d+\s+[^\.,;!\?]+)$",
            r"\b(mais\s+carne\b.*)$",
            r"\b(sem\s+[^\.,;!\?]+)$",
            r"\b(com\s+[^\.,;!\?]+)$",
            r"\b(retirar\b.*)$",
            r"\b(tirar\b.*)$",
            r"\b(trocar\b.*)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, original, flags=re.IGNORECASE)
            if match:
                observation = (match.group(1) or "").strip(" ,;:-")
                return observation
        return ""

    def _is_possible_order_observation(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        if self._is_local_pickup(normalized) or self._looks_like_address(normalized):
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
            "com ",
            "retirar",
            "tirar",
            "trocar",
        ]
        return any(marker in normalized for marker in markers)

    def _observation_may_have_extra_charge(self, observation: str) -> bool:
        normalized = self._normalize(observation)
        if not normalized:
            return False
        if normalized.startswith(("sem ", "retirar", "tirar", "trocar")):
            return False
        return any(
            marker in normalized
            for marker in [
                "acrescent",
                "adicion",
                "colocar mais",
                "extra",
                "adicional",
                "mais ",
            ]
        )

    def _attach_observation_to_item(self, item: dict | None, observation: str) -> dict | None:
        if item is None or not observation:
            return item
        item = item.copy()
        existing = (item.get("observacao") or "").strip()
        combined = observation.strip()
        if existing and combined.lower() not in existing.lower():
            combined = f"{existing}; {combined}"
        elif existing:
            combined = existing
        item["observacao"] = combined
        if self._observation_may_have_extra_charge(combined):
            item["observacao_pode_ter_cobranca_extra"] = True
        return item

    def _items_have_pending_additional_review(self, items: list[dict]) -> bool:
        return any(bool(item.get("observacao_pode_ter_cobranca_extra")) for item in items)

    def _observation_review_prompt(self) -> str:
        return (
            "Só para confirmar: esse adicional pode ter cobrança extra. "
            "Deseja que eu consulte a atendente ou posso continuar com o pedido?"
        )

    def _apply_observation_to_current_order(self, telefone: str, state, observation: str) -> dict | None:
        if not observation or not state.itens_pedido:
            return None

        items = list(state.itens_pedido or [])
        items[-1] = self._attach_observation_to_item(items[-1], observation)
        has_pending_additional_review = self._items_have_pending_additional_review(items)

        update_fields = {
            "itens_pedido": items,
        }
        if has_pending_additional_review:
            update_fields["status_atendimento"] = AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM
            update_fields["aguardando_resposta"] = "confirmacao_item"
        update_state(telefone, **update_fields)

        refreshed = get_or_create_state(telefone)
        pricing = {
            "can_calculate": bool(refreshed.valor_total),
            "needs_owner": False,
            "unit_price": refreshed.valor_unitario,
            "total_price": refreshed.valor_total,
        }
        if has_pending_additional_review:
            response = self._build_items_summary_response(
                items=refreshed.itens_pedido,
                total=refreshed.valor_total,
                ask_address=False,
                show_partial_label=True,
            )
            response = f"{response}\n\n{self._observation_review_prompt()}"
            return {
                "state": asdict(refreshed),
                "pricing": pricing,
                "next_question": self._observation_review_prompt(),
                "response": response,
            }

        next_question = self._next_question(refreshed, pricing)
        current_state = get_or_create_state(telefone)
        update_state(telefone, aguardando_resposta=self._awaiting_field(current_state, pricing))
        response = self._build_items_summary_response(
            items=current_state.itens_pedido,
            total=current_state.valor_total,
            ask_address=False,
        )
        response = f"{response}\n\n{next_question}"
        return {
            "state": asdict(get_or_create_state(telefone)),
            "pricing": pricing,
            "next_question": next_question,
            "response": response,
        }

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
            self.persist_order_snapshot(telefone, mark_cancelled=True)
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
                "response": "Pedido cancelado. Se precisar de algo mais, é só me chamar.",
            }

        if state.aguardando_resposta == "complemento":
            options = self._list_available_complements()
            if not options:
                return self._finish_complement_stage(telefone)

            if self._is_negative_complement_answer(normalized, self._complement_skip_choice(options)):
                return self._finish_complement_stage(telefone)

            selected_option = self._extract_complement_choice(normalized, options)
            if selected_option is None:
                prompt = self._complement_prompt()
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": prompt,
                    "response": prompt,
                }

            selected_qty = self._to_int(message) or self._to_int(normalized)
            if self._should_add_complement_immediately(message, selected_qty, selected_option):
                return self._add_complement_to_order(telefone, selected_option, selected_qty)

            update_state(
                telefone,
                itens_pendentes=[selected_option],
                aguardando_resposta="quantidade_complemento",
            )
            refreshed = get_or_create_state(telefone)
            quantity_prompt = self._prompt_complement_quantity(selected_option)
            return {
                "state": asdict(refreshed),
                "pricing": {
                    "can_calculate": bool(refreshed.valor_total),
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                },
                "next_question": quantity_prompt,
                "response": quantity_prompt,
            }

        if state.aguardando_resposta == "quantidade_complemento":
            pending_option = self._find_pending_complement(state)
            if pending_option is None:
                update_state(telefone, aguardando_resposta="complemento", itens_pendentes=[])
                prompt = self._complement_prompt()
                return {
                    "state": asdict(get_or_create_state(telefone)),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": prompt,
                    "response": prompt,
                }

            selected_qty = self._to_int(message) or self._to_int(normalized)
            if not selected_qty:
                quantity_prompt = self._prompt_complement_quantity(pending_option)
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": quantity_prompt,
                    "response": quantity_prompt,
                }
            return self._add_complement_to_order(telefone, pending_option, selected_qty)

        if state.aguardando_resposta == "mais_complementos":
            if self._is_negative_complement_answer(normalized, "2"):
                return self._finish_complement_stage(telefone)

            options = self._list_available_complements()
            selected_option = self._extract_complement_choice(normalized, options)
            if selected_option is not None:
                selected_qty = self._to_int(message) or self._to_int(normalized)
                if self._should_add_complement_immediately(message, selected_qty, selected_option):
                    return self._add_complement_to_order(telefone, selected_option, selected_qty)
                update_state(
                    telefone,
                    itens_pendentes=[selected_option],
                    aguardando_resposta="quantidade_complemento",
                )
                refreshed = get_or_create_state(telefone)
                quantity_prompt = self._prompt_complement_quantity(selected_option)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": quantity_prompt,
                    "response": quantity_prompt,
                }

            if self._is_positive_more_complements_answer(normalized):
                update_state(telefone, aguardando_resposta="complemento")
                refreshed = get_or_create_state(telefone)
                prompt = self._complement_prompt()
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": prompt,
                    "response": prompt,
                }

            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": self._more_complements_prompt(),
                "response": self._more_complements_prompt(),
            }

        if self._is_waiting_marmita_type(state):
            type_choice = self._extract_marmita_type_choice(normalized)
            if type_choice is None:
                clarification = (
                    "Não consegui identificar o tipo de marmita.\n\n"
                    f"{self._marmita_type_prompt()}"
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
                item = self._attach_observation_to_item(item, self._extract_order_observation(message))
                if item is None:
                    return self._catalog_unavailable_response(telefone, "Marmitex individual")
                return self._apply_order_items(telefone, [item])

        if (
            state.itens_pedido
            and self._is_possible_order_observation(message)
            and not self._extract_payment(text)
            and not self._looks_like_address(text)
        ):
            observation_result = self._apply_observation_to_current_order(
                telefone,
                state,
                self._extract_order_observation(message),
            )
            if observation_result is not None:
                return observation_result

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_PESSOAS_MARMITA:
            people = self._extract_people_count_for_pending_family(normalized)
            if people:
                if people > self._owner_threshold():
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
                        "next_question": self._owner_consultation_message(),
                        "response": self._owner_consultation_message(),
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
                "next_question": self._family_people_prompt(),
                "response": self._family_people_prompt(),
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
                current_state = get_or_create_state(telefone)
                aguardando = self._awaiting_field(current_state, pricing)
                update_state(telefone, aguardando_resposta=aguardando)
                response = self._build_response(get_or_create_state(telefone), pricing, next_question)
                return {
                    "state": asdict(get_or_create_state(telefone)),
                    "pricing": pricing,
                    "next_question": next_question,
                    "response": response,
                }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_NOME_CLIENTE:
            customer_name = self._set_customer_name(telefone, message)
            if not customer_name:
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": self._invalid_customer_name_prompt(),
                    "response": self._invalid_customer_name_prompt(),
                }
            update_state(
                telefone,
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
                "next_question": self._payment_options_prompt(),
                "response": self._payment_summary_response(refreshed, customer_name),
            }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFIRMACAO:
            if self._is_cancel_request(normalized):
                self.persist_order_snapshot(telefone, mark_cancelled=True)
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
                    "response": "Pedido cancelado. Se precisar de algo mais, é só me chamar.",
                }
            if self._is_final_order_change_request(message):
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": "Sem problema 😊 O que você deseja alterar: itens, entrega/retirada, endereço, nome ou pagamento?",
                    "response": "Sem problema 😊 O que você deseja alterar: itens, entrega/retirada, endereço, nome ou pagamento?",
                }
            if self._is_final_order_confirmation(message):
                refreshed = get_or_create_state(telefone)
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": "",
                    "response": self._build_confirmed_order_response(refreshed),
                }
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": "Posso seguir com esse pedido? Se estiver tudo certo, me confirme por favor.",
                "response": self._build_order_summary(state),
            }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA:
            if self._is_cancel_request(normalized):
                self.persist_order_snapshot(telefone, mark_cancelled=True)
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
                    "response": "Pedido cancelado. Se precisar de algo mais, é só me chamar.",
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
                    "next_question": self._family_people_prompt(),
                    "response": (
                        f"{partial}\n\n" if partial else ""
                    ) + self._family_people_prompt(),
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
                        self._delivery_mode_prompt()
                    ),
                    "response": (
                        "A taxa de entrega depende do endereço. "
                        "Se você escolher entrega, me envie o endereço para confirmarmos certinho.\n\n"
                        f"{self._delivery_mode_prompt()}"
                    ),
                }
            if self._is_delivery_choice(normalized):
                if not self._business_settings().aceita_entrega:
                    return {
                        "state": asdict(state),
                        "pricing": {
                            "can_calculate": bool(state.valor_total),
                            "needs_owner": False,
                            "unit_price": state.valor_unitario,
                            "total_price": state.valor_total,
                        },
                        "next_question": self._delivery_mode_prompt(),
                        "response": f"Entrega indisponível no momento.\n\n{self._delivery_mode_prompt()}",
                    }
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
                    "next_question": (
                        "Perfeito 😊 Vou marcar como entrega.\n\n"
                        f"{self._delivery_address_prompt()}"
                    ),
                    "response": (
                        "Perfeito 😊 Vou marcar como entrega.\n\n"
                        f"{self._delivery_address_prompt()}"
                    ),
                }
            if self._is_pickup_choice(normalized):
                if not self._business_settings().aceita_retirada_local:
                    return {
                        "state": asdict(state),
                        "pricing": {
                            "can_calculate": bool(state.valor_total),
                            "needs_owner": False,
                            "unit_price": state.valor_unitario,
                            "total_price": state.valor_total,
                        },
                        "next_question": self._delivery_mode_prompt(),
                        "response": f"Retirada no local indisponível no momento.\n\n{self._delivery_mode_prompt()}",
                    }
                update_state(
                    telefone,
                    tipo_entrega="retirada",
                    endereco="retirada no local",
                    status_atendimento=AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
                    aguardando_resposta="nome_cliente",
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
                    "next_question": self._customer_name_prompt(),
                    "response": (
                        f"{self._pickup_confirmation_text()}\n\n"
                        f"{self._customer_name_prompt()}"
                    ),
                }
            if self._looks_like_address(text):
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    endereco=message.strip(),
                    status_atendimento=AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
                    aguardando_resposta="nome_cliente",
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
                    "next_question": self._customer_name_prompt(),
                    "response": f"Perfeito 😊 Endereço anotado. {self._customer_name_prompt()}",
                }
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": self._delivery_mode_prompt(),
                "response": self._delivery_mode_prompt(),
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
                    "A taxa de entrega depende do endereço. "
                    "Me envie o endereço de entrega para confirmarmos o valor certinho."
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

        if self._is_local_pickup(normalized) and "marmita" not in normalized and "marmitex" not in normalized:
            update_state(
                telefone,
                tipo_entrega="retirada",
                endereco="retirada no local",
                status_atendimento=AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
                aguardando_resposta="nome_cliente",
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
                "next_question": self._customer_name_prompt(),
                "response": (
                    f"{self._pickup_confirmation_text()}\n\n"
                    f"{self._customer_name_prompt()}"
                ),
            }

        if self._is_total_question(text) and state.produto and state.quantidade and state.valor_total > 0:
            waiting_status = AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA
            waiting_question = (
                self._delivery_mode_prompt()
            )
            if state.aguardando_resposta == "complemento":
                waiting_question = self._complement_prompt()
            elif state.aguardando_resposta == "mais_complementos":
                waiting_question = self._more_complements_prompt()
            elif state.aguardando_resposta == "quantidade_complemento":
                pending_option = self._find_pending_complement(state)
                waiting_question = (
                    self._prompt_complement_quantity(pending_option)
                    if pending_option is not None
                    else self._complement_prompt()
                )
            if state.tipo_entrega == "entrega":
                waiting_status = AtendimentoStatus.AGUARDANDO_ENDERECO
                waiting_question = self._delivery_address_prompt()
            elif state.tipo_entrega == "retirada":
                waiting_status = AtendimentoStatus.AGUARDANDO_NOME_CLIENTE
                waiting_question = self._customer_name_prompt()
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
                    self._owner_consultation_message()
                ),
                "response": self._owner_consultation_message(),
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
                "next_question": self._family_people_prompt(),
                "response": (
                    f"{partial}\n\n" if partial else ""
                ) + self._family_people_prompt(),
            }

        if items_data["items"]:
            result = self._apply_order_items(telefone, items_data["items"])
            if self._is_local_pickup(normalized):
                update_state(telefone, tipo_entrega="retirada", endereco="retirada no local")
                result["state"] = asdict(get_or_create_state(telefone))
            elif self._looks_like_address(text):
                update_state(telefone, tipo_entrega="entrega", endereco=message.strip())
                result["state"] = asdict(get_or_create_state(telefone))
            elif self._looks_like_delivery(normalized):
                update_state(telefone, tipo_entrega="entrega")
                result["state"] = asdict(get_or_create_state(telefone))
            return result

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM:
            if self._is_positive_confirmation(text):
                refreshed = get_or_create_state(telefone)
                pricing = {
                    "can_calculate": bool(refreshed.valor_total),
                    "needs_owner": False,
                    "unit_price": refreshed.valor_unitario,
                    "total_price": refreshed.valor_total,
                }
                next_question = self._next_question(refreshed, pricing)
                current_state = get_or_create_state(telefone)
                update_state(telefone, aguardando_resposta=self._awaiting_field(current_state, pricing))
                return {
                    "state": asdict(get_or_create_state(telefone)),
                    "pricing": pricing,
                    "next_question": next_question,
                    "response": next_question,
                }
            return {
                "state": asdict(state),
                "pricing": {
                    "can_calculate": bool(state.valor_total),
                    "needs_owner": False,
                    "unit_price": state.valor_unitario,
                    "total_price": state.valor_total,
                },
                "next_question": self._observation_review_prompt(),
                "response": self._observation_review_prompt(),
            }

        if state.status_atendimento == AtendimentoStatus.AGUARDANDO_COMPROVANTE:
            if self._is_receipt_pending_acknowledgement(text) and not file_name and not file_mimetype:
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": "Envie o comprovante por imagem, PDF ou texto do comprovante.",
                    "response": "Tudo bem 😊 Fico aguardando o comprovante por aqui.",
                }
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
                    "next_question": "O comprovante será conferido antes da confirmação do pedido.",
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
                    "Ainda preciso receber o comprovante para seguir com a conferência do pagamento.\n\n"
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
                "next_question": "Aguarde a conferência do comprovante.",
                "response": (
                    "Seu comprovante já foi recebido e está aguardando conferência. "
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
            if state.aguardando_resposta in {"complemento", "quantidade_complemento", "mais_complementos"}:
                return None
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
            item = self._attach_observation_to_item(item, self._extract_order_observation(message))
            if item is None:
                return self._catalog_unavailable_response(telefone, "item selecionado")
            return self._apply_order_items(telefone, [item])

        if intencao == "informar_retirada" and in_order:
            if not self._business_settings().aceita_retirada_local:
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": self._delivery_mode_prompt(),
                    "response": f"Retirada no local indisponível no momento.\n\n{self._delivery_mode_prompt()}",
                }
            if state.aguardando_resposta in {"complemento", "quantidade_complemento", "mais_complementos"}:
                update_state(
                    telefone,
                    tipo_entrega="retirada",
                    endereco="retirada no local",
                    ultima_intencao="fazer_pedido",
                )
                refreshed = get_or_create_state(telefone)
                prompt = (
                    self._prompt_complement_quantity(self._find_pending_complement(refreshed))
                    if refreshed.aguardando_resposta == "quantidade_complemento" and self._find_pending_complement(refreshed)
                    else (self._more_complements_prompt() if refreshed.aguardando_resposta == "mais_complementos" else self._complement_prompt())
                )
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": prompt,
                    "response": prompt,
                }
            update_state(
                telefone,
                tipo_entrega="retirada",
                endereco="retirada no local",
                status_atendimento=AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
                aguardando_resposta="nome_cliente",
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
                "next_question": self._customer_name_prompt(),
                "response": (
                    f"{self._pickup_confirmation_text()}\n\n"
                    f"{self._customer_name_prompt()}"
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
            clarification = self._marmita_type_prompt()
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
            if not self._business_settings().aceita_entrega:
                return {
                    "state": asdict(state),
                    "pricing": {
                        "can_calculate": bool(state.valor_total),
                        "needs_owner": False,
                        "unit_price": state.valor_unitario,
                        "total_price": state.valor_total,
                    },
                    "next_question": self._delivery_mode_prompt(),
                    "response": f"Entrega indisponível no momento.\n\n{self._delivery_mode_prompt()}",
                }
            if state.aguardando_resposta in {"complemento", "quantidade_complemento", "mais_complementos"}:
                update_fields = {
                    "tipo_entrega": "entrega",
                    "ultima_intencao": "fazer_pedido",
                }
                if endereco:
                    update_fields["endereco"] = endereco
                update_state(telefone, **update_fields)
                refreshed = get_or_create_state(telefone)
                prompt = (
                    self._prompt_complement_quantity(self._find_pending_complement(refreshed))
                    if refreshed.aguardando_resposta == "quantidade_complemento" and self._find_pending_complement(refreshed)
                    else (self._more_complements_prompt() if refreshed.aguardando_resposta == "mais_complementos" else self._complement_prompt())
                )
                return {
                    "state": asdict(refreshed),
                    "pricing": {
                        "can_calculate": bool(refreshed.valor_total),
                        "needs_owner": False,
                        "unit_price": refreshed.valor_unitario,
                        "total_price": refreshed.valor_total,
                    },
                    "next_question": prompt,
                    "response": prompt,
                }
            if tipo_entrega == "entrega" and not endereco:
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    status_atendimento=AtendimentoStatus.AGUARDANDO_ENDERECO,
                    aguardando_resposta="endereco",
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
                    "next_question": self._delivery_address_prompt(),
                    "response": self._delivery_address_prompt(),
                }
            if endereco:
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    endereco=endereco,
                    status_atendimento=AtendimentoStatus.AGUARDANDO_NOME_CLIENTE,
                    aguardando_resposta="nome_cliente",
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
                    "next_question": self._customer_name_prompt(),
                    "response": f"Perfeito 😊 Endereço anotado. {self._customer_name_prompt()}",
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
            clarification = self._marmita_type_prompt()
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
            if people and people > self._owner_threshold():
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
        item = self._attach_observation_to_item(item, self._extract_order_observation(message))
        if item is None:
            human_name = "marmita selecionada" if produto_key != "marmitex_individual" else "marmitex individual"
            return self._catalog_unavailable_response(telefone, human_name)

        result = self._apply_order_items(telefone, [item])
        if tipo_entrega == "retirada":
            update_state(
                telefone,
                tipo_entrega="retirada",
                endereco="retirada no local",
            )
            refreshed = get_or_create_state(telefone)
            result["state"] = asdict(refreshed)
            result["pricing"]["unit_price"] = refreshed.valor_unitario
            result["pricing"]["total_price"] = refreshed.valor_total
        elif tipo_entrega == "entrega":
            if endereco:
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                    endereco=endereco,
                )
                refreshed = get_or_create_state(telefone)
                result["state"] = asdict(refreshed)
                result["pricing"]["unit_price"] = refreshed.valor_unitario
                result["pricing"]["total_price"] = refreshed.valor_total
            else:
                update_state(
                    telefone,
                    tipo_entrega="entrega",
                )
                refreshed = get_or_create_state(telefone)
                result["state"] = asdict(refreshed)
                result["pricing"]["unit_price"] = refreshed.valor_unitario
                result["pricing"]["total_price"] = refreshed.valor_total
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
            update_state(telefone, endereco="retirada no local")
            current = get_or_create_state(telefone)
            result["state"] = asdict(current)
            return result

        if refreshed.tipo_entrega == "entrega" and not refreshed.endereco:
            current = get_or_create_state(telefone)
            result["state"] = asdict(current)
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
                "next_question": "Quantas marmitex individuais você deseja?",
                "response": "Perfeito 😊 Quantas marmitex individuais você deseja?",
            }

        people = int(selected_choice["people_count"])
        if people > self._owner_threshold():
            update_state(
                telefone,
                ultima_intencao="fazer_pedido",
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
                "next_question": self._owner_consultation_message(),
                "response": self._owner_consultation_message(),
            }
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
            "produto_id": getattr(catalog_item.get("produto"), "id", None),
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
        has_pending_additional_review = self._items_have_pending_additional_review(items)
        complement_prompt = self._complement_prompt()
        waiting_for_complement = bool(items) and not has_pending_additional_review and bool(self._list_available_complements())
        update_state(
            telefone,
            ultima_intencao="fazer_pedido",
            status_atendimento=(
                AtendimentoStatus.AGUARDANDO_CONFIRMACAO_ITEM
                if has_pending_additional_review
                else AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA
            ),
            itens_pedido=items,
            produto=first["produto_key"],
            quantidade=first["quantidade"],
            valor_unitario=first["valor_unitario"],
            valor_total=total_price,
            aguardando_resposta=(
                "confirmacao_item"
                if has_pending_additional_review
                else ("complemento" if waiting_for_complement else "tipo_entrega")
            ),
            **pending_fields,
        )
        refreshed = get_or_create_state(telefone)
        response = self._build_items_summary_response(
            items=refreshed.itens_pedido,
            total=refreshed.valor_total,
            ask_address=False,
            show_partial_label=has_pending_additional_review or waiting_for_complement,
        )
        if has_pending_additional_review:
            response = f"{response}\n\n{self._observation_review_prompt()}"
        elif waiting_for_complement:
            response = f"{response}\n\n{complement_prompt}"
        elif not refreshed.tipo_entrega:
            response = f"{response}\n\n{self._delivery_mode_prompt()}"
        return {
            "state": asdict(refreshed),
            "pricing": {
                "can_calculate": True,
                "needs_owner": False,
                "unit_price": refreshed.valor_unitario,
                "total_price": refreshed.valor_total,
            },
            "next_question": (
                self._observation_review_prompt()
                if has_pending_additional_review
                else (complement_prompt if waiting_for_complement else self._delivery_mode_prompt())
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

    def _is_final_order_confirmation(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        return normalized in {
            "sim",
            "pode",
            "pode sim",
            "ok",
            "okay",
            "certo",
            "confirmo",
            "confirmar",
            "esta certo",
            "ta certo",
            "isso",
            "isso mesmo",
            "pode seguir",
            "fechado",
            "beleza",
        }

    def _is_final_order_change_request(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        return normalized in {
            "nao",
            "não",
            "quero alterar",
            "alterar",
            "mudar",
            "corrigir",
        }

    def _is_receipt_pending_acknowledgement(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        return normalized in {
            "ok",
            "okay",
            "certo",
            "ta bom",
            "tá bom",
            "beleza",
            "vou enviar",
            "vou mandar",
            "ja mando",
            "ja envio",
            "envio ja",
        }

    def _pix_payment_instructions(self, state) -> str:
        business = self._business_settings()
        total = format_brl(state.valor_total or 0)
        pix_key = (business.chave_pix or "").strip() or "Chave Pix ainda não configurada no sistema."
        payee = (business.nome_empresa or "").strip() or "Marmitaria da Adriana"
        if payee == "Marmitaria Adriana":
            payee = "Marmitaria da Adriana"

        return (
            "Perfeito 😊 Pagamento via Pix.\n\n"
            f"Valor do pedido: {total}\n\n"
            f"Chave Pix:\n{pix_key}\n\n"
            f"Favorecido:\n{payee}\n\n"
            "Depois de fazer o Pix, envie o comprovante por aqui para conferirmos o pagamento."
        )

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
            if people > self._owner_threshold():
                product = "marmita_acima_5_pessoas"
            elif people == 2:
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

            if people > self._owner_threshold():
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

        observation = self._extract_order_observation(text)
        grouped_items = list(grouped.values())
        if observation and len(grouped_items) == 1:
            grouped_items[0] = self._attach_observation_to_item(grouped_items[0], observation)

        return {
            "items": grouped_items,
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
        if t in NUMBER_WORDS:
            return NUMBER_WORDS[t]
        for part in t.split():
            if part.isdigit():
                return int(part)
            if part in NUMBER_WORDS:
                return NUMBER_WORDS[part]
        return None

    def _extract_payment(self, text: str) -> str:
        normalized = self._normalize(text)
        if normalized in {"1", "pix"} or "pix" in normalized:
            return "Pix"
        if normalized in {"2", "dinheiro"} or "dinheiro" in normalized:
            return "Dinheiro"
        if normalized in {"3", "cartao"} or "cartao" in normalized:
            return "Cartão"
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
                lines.append("No momento a marmitex individual não está disponível.")
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
                    lines.append(f"No momento a marmita para {people} pessoas não está disponível.")
                has_specific = True

        if not has_specific:
            available_products = list_order_products(only_available=True)
            if available_products:
                lines = ["Nossos valores sao:\n"]
                for product in available_products:
                    lines.append(f"* {product['nome']}: {format_brl(product['preco'])}")
                lines.append(f"\n{self._owner_consultation_message()}")
            else:
                lines = ["No momento não há opções de pedido disponíveis no catálogo."]

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

    def _looks_like_delivery(self, normalized_text: str) -> bool:
        return any(term in normalized_text for term in ["entrega", "entregar", "para entregar"])

    def _is_delivery_choice(self, normalized_text: str) -> bool:
        return normalized_text in {"1", "entrega", "quero entrega", "entregar"}

    def _is_pickup_choice(self, normalized_text: str) -> bool:
        if normalized_text == "2":
            return True
        return self._is_local_pickup(normalized_text) or normalized_text in {"retirada", "retirar"}

    def _looks_like_address(self, text: str) -> bool:
        return any(k in text for k in ["rua", "av", "avenida", "travessa", "bairro", "numero", "nº", "cep"])

    def _product_selection_prompt(self) -> str:
        choices = [
            item
            for item in get_order_product_choices()
            if item["key"] == "marmitex_individual" or item["people_count"] <= self._owner_threshold()
        ]
        if not choices:
            return (
                "No momento não há produtos de pedido disponíveis no catálogo. "
                "Pode falar com a atendente para ajustar a disponibilidade."
            )

        lines = ["Você deseja:"]
        for item in choices:
            lines.append(f"{item['choice']} - {item['nome']}")
        lines.append("")
        lines.append('Ou, se preferir, me diga direto a quantidade. Exemplo: "quero 3 marmitex".')
        return "\n".join(lines)

    def _catalog_unavailable_response(self, telefone: str, product_name: str) -> dict:
        response = (
            f"No momento {product_name.lower()} não está disponível. "
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
        if state.itens_pedido and not state.tipo_entrega and state.aguardando_resposta != "tipo_entrega":
            return "complemento"
        if not state.tipo_entrega:
            return "tipo_entrega"
        if state.tipo_entrega != "retirada" and not state.endereco:
            return "endereco"
        if not self._get_customer_name(state.telefone):
            return "nome_cliente"
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
            return self._owner_consultation_message()
        if waiting == "complemento":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
            return self._complement_prompt()
        if waiting == "tipo_entrega":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_TIPO_ENTREGA)
            return self._delivery_mode_prompt()
        if waiting == "endereco":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_ENDERECO)
            return self._delivery_address_prompt()
        if waiting == "nome_cliente":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_NOME_CLIENTE)
            return self._customer_name_prompt()
        if waiting == "forma_pagamento":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_PAGAMENTO)
            return "Qual será a forma de pagamento? Pix, dinheiro ou cartão?"
        if waiting == "comprovante":
            update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_COMPROVANTE)
            return self._pix_payment_instructions(state)

        update_state(state.telefone, status_atendimento=AtendimentoStatus.AGUARDANDO_CONFIRMACAO)
        return "Posso seguir com esse pedido? Se estiver tudo certo, me confirme por favor."

    def _build_response(self, state, pricing: dict, next_question: str) -> str:
        if pricing.get("needs_owner"):
            return next_question

        if state.itens_pedido and pricing.get("can_calculate"):
            if state.endereco and not self._get_customer_name(state.telefone):
                return f"Perfeito 😊 Endereço anotado. {self._customer_name_prompt()}"
            if state.endereco and not state.forma_pagamento:
                return "Perfeito 😊 Endereço anotado. Qual será a forma de pagamento? Pix, dinheiro ou cartão?"
            if state.forma_pagamento and state.forma_pagamento != "Pix":
                return self._build_order_summary(state)
            if state.forma_pagamento == "Pix":
                return self._pix_payment_instructions(state)
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
                    f"{self._delivery_mode_prompt()}"
                )
            if state.tipo_entrega != "retirada" and not state.endereco:
                produto = self._human_product_name(state.produto, state.quantidade)
                return (
                    f"Perfeito 😊 {produto} ficam em {total}. "
                    f"{self._delivery_address_prompt()}"
                )
            if not self._get_customer_name(state.telefone):
                return f"Perfeito! Valor parcial do pedido: {total}. {self._customer_name_prompt()}"
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
        customer_name = self._get_customer_name(state.telefone)
        if state.itens_pedido:
            itens = "\n".join(line.replace("* ", "• ") for line in self._order_item_lines(state))
            receiving_lines = [f"• Forma de recebimento: {self._receiving_label(state)}"]
            if state.tipo_entrega == "entrega" and state.endereco:
                receiving_lines.append(f"• Endereço: {state.endereco}")
            if customer_name:
                receiving_lines.append(f"• Nome: {customer_name}")
            return (
                "Resumo do seu pedido:\n\n"
                f"{itens}\n"
                + "\n".join(receiving_lines)
                + "\n"
                f"• Forma de pagamento: {state.forma_pagamento}\n\n"
                f"Total: {total}\n\n"
                "Posso seguir com esse pedido?\n"
                "Se estiver tudo certo, me confirme por favor."
            )

        produto_legivel = self._human_product_name(state.produto, state.quantidade)
        receiving_lines = [f"• Forma de recebimento: {self._receiving_label(state)}"]
        if state.tipo_entrega == "entrega" and state.endereco:
            receiving_lines.append(f"• Endereço: {state.endereco}")
        if customer_name:
            receiving_lines.append(f"• Nome: {customer_name}")
        return (
            "Resumo do seu pedido:\n\n"
            f"• {produto_legivel}\n"
            + "\n".join(receiving_lines)
            + "\n"
            f"• Forma de pagamento: {state.forma_pagamento}\n\n"
            f"Total: {total}\n\n"
            "Posso seguir com esse pedido?\n"
            "Se estiver tudo certo, me confirme por favor."
        )

    def _build_confirmed_order_response(self, state) -> str:
        total = f"R$ {state.valor_total:.2f}".replace(".", ",")
        customer_name = self._get_customer_name(state.telefone)
        lines = ["Pedido confirmado com sucesso 😊", "", "Resumo do pedido:", ""]
        lines.extend(self._order_item_lines(state))
        lines.append("")
        lines.append(f"* Forma de recebimento: {self._receiving_label(state)}")
        if state.tipo_entrega == "entrega" and state.endereco:
            lines.append(f"* Endereço: {state.endereco}")
        if customer_name:
            lines.append(f"* Nome: {customer_name}")
        lines.append(f"* Forma de pagamento: {state.forma_pagamento}")
        lines.extend(["", f"Total: {total}", ""])

        if state.tipo_entrega == "retirada" and customer_name:
            lines.append(
                f"A equipe da Marmitaria da Adriana já pode preparar seu pedido. "
                f"Quando chegar, informe o nome {customer_name} para retirar."
            )
        elif state.tipo_entrega == "entrega":
            lines.append(
                "A equipe da Marmitaria da Adriana já pode preparar seu pedido. "
                "Vamos preparar seu pedido para entrega no endereço informado."
            )
        else:
            lines.append("A equipe da Marmitaria da Adriana já pode preparar seu pedido.")
        return "\n".join(lines)

    def _build_payment_proof_received_response(self, state) -> str:
        total = f"R$ {state.valor_total:.2f}".replace(".", ",")
        lines = [
            "Comprovante recebido 😊",
            "",
            "Vou deixar o pagamento em conferência. Por segurança, ainda não confirmo o pagamento automaticamente por aqui.",
        ]
        if state.itens_pedido:
            item_lines = []
            for item in state.itens_pedido:
                subtotal = f"R$ {float(item['subtotal']):.2f}".replace(".", ",")
                qty = int(item["quantidade"])
                produto = self._pluralize_produto(item["produto"], qty)
                item_lines.append(f"* {qty} {produto}: {subtotal}")
                observation = (item.get("observacao") or "").strip()
                if observation:
                    item_lines.append(f"* Observação: {observation}")
            lines.extend(["", "Resumo do pedido:", *item_lines, f"Total: {total}"])
        elif state.produto:
            produto_legivel = self._human_product_name(state.produto, state.quantidade)
            lines.extend(["", "Resumo do pedido:", f"* {produto_legivel}", f"Total: {total}"])
        lines.append("")
        lines.append("A equipe precisa validar o comprovante antes de confirmar o pedido.")
        return "\n".join(lines)

    def _build_items_summary_response(
        self,
        items: list[dict],
        total: float,
        ask_address: bool,
        show_partial_label: bool = False,
        title: str = "Perfeito 😊 Seu pedido ficou assim:",
    ) -> str:
        lines = [title, ""]
        for item in items:
            subtotal = f"R$ {float(item['subtotal']):.2f}".replace(".", ",")
            qty = int(item["quantidade"])
            produto = item["produto"]
            produto_label = self._pluralize_produto(produto, qty)
            if qty == 1:
                lines.append(f"* 1 {produto}: {subtotal}")
            else:
                lines.append(f"* {qty} {produto_label}: {subtotal}")
            observation = (item.get("observacao") or "").strip()
            if observation:
                lines.append(f"* Observação: {observation}")
        total_str = f"R$ {float(total):.2f}".replace(".", ",")
        lines.append("")
        total_label = "Total parcial" if show_partial_label else "Total"
        lines.append(f"{total_label}: {total_str}")
        if ask_address:
            lines.extend(["", self._delivery_mode_prompt()])
        return "\n".join(lines)

    def _pluralize_produto(self, produto: str, quantidade: int) -> str:
        if quantidade <= 1:
            return produto
        if produto == "marmitex individual":
            return "marmitex individuais"
        if produto.startswith("marmita para "):
            return produto.replace("marmita para ", "marmitas para ", 1)
        if produto in {"agua mineral", "água mineral"}:
            return "águas minerais" if "á" in produto else "aguas minerais"
        if produto == "ovo adicional":
            return "ovos adicionais"
        if produto == "sobremesa do dia":
            return "sobremesas do dia"
        return produto

    def _marmita_type_prompt(self) -> str:
        choices = [
            item
            for item in get_order_product_choices()
            if item["key"] == "marmitex_individual" or item["people_count"] <= self._owner_threshold()
        ]
        lines = ["Você deseja:", ""]
        for item in choices:
            lines.append(f"{item['choice']} - {item['nome']}")
        return "\n".join(lines)


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

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .states import AwaitingResponse


Matcher = Callable[[str], bool]


@dataclass(frozen=True)
class TransitionRule:
    current: str
    next: str
    matcher: Matcher
    description: str


def _is_exact(expected: str) -> Matcher:
    return lambda message: message == expected


def _contains_any(*parts: str) -> Matcher:
    return lambda message: any(part in message for part in parts)


def _any_non_empty(message: str) -> bool:
    return bool(message.strip())


TRANSITION_RULES: list[TransitionRule] = [
    TransitionRule(
        current=AwaitingResponse.MENU_PRINCIPAL.value,
        next=AwaitingResponse.PRODUTO.value,
        matcher=_is_exact("1"),
        description='No menu principal, "1" inicia o pedido.',
    ),
    TransitionRule(
        current=AwaitingResponse.PRODUTO.value,
        next=AwaitingResponse.QUANTIDADE.value,
        matcher=_is_exact("1"),
        description='Na seleção de produto, "1" escolhe Marmitex individual.',
    ),
    TransitionRule(
        current=AwaitingResponse.PRODUTO.value,
        next=AwaitingResponse.COMPLEMENTO.value,
        matcher=_contains_any("marmita para 2 pessoas", "marmita para 3 pessoas", "marmita para 4 pessoas", "marmita para 5 pessoas"),
        description="Pedido textual de marmita familiar vai direto para complementos.",
    ),
    TransitionRule(
        current=AwaitingResponse.QUANTIDADE.value,
        next=AwaitingResponse.COMPLEMENTO.value,
        matcher=_is_exact("2"),
        description='Na quantidade, "2" fecha 2 unidades e abre complementos.',
    ),
    TransitionRule(
        current=AwaitingResponse.COMPLEMENTO.value,
        next=AwaitingResponse.TIPO_ENTREGA.value,
        matcher=_contains_any("nao quero", "não quero", "sem bebida", "pode seguir", "sem nada"),
        description="Recusa complemento e segue para entrega ou retirada.",
    ),
    TransitionRule(
        current=AwaitingResponse.COMPLEMENTO.value,
        next=AwaitingResponse.MAIS_COMPLEMENTOS.value,
        matcher=_contains_any("quero uma agua", "quero uma água", "quero 2 refrigerantes", "quero 2 ovos adicionais"),
        description="Complemento com quantidade explícita ou implícita atualiza pedido e abre confirmação de mais itens.",
    ),
    TransitionRule(
        current=AwaitingResponse.COMPLEMENTO.value,
        next=AwaitingResponse.QUANTIDADE_COMPLEMENTO.value,
        matcher=lambda message: message in {"1", "2", "3", "4"},
        description="Seleção numérica de complemento pede a quantidade do item.",
    ),
    TransitionRule(
        current=AwaitingResponse.MAIS_COMPLEMENTOS.value,
        next=AwaitingResponse.TIPO_ENTREGA.value,
        matcher=_contains_any("nao quero mais nada", "não quero mais nada", "pode seguir", "seguir pedido"),
        description="Após complementos, cliente decide seguir para entrega ou retirada.",
    ),
    TransitionRule(
        current=AwaitingResponse.TIPO_ENTREGA.value,
        next=AwaitingResponse.ENDERECO.value,
        matcher=_is_exact("1"),
        description='Na entrega/retirada, "1" significa entrega.',
    ),
    TransitionRule(
        current=AwaitingResponse.TIPO_ENTREGA.value,
        next=AwaitingResponse.NOME_CLIENTE.value,
        matcher=_is_exact("2"),
        description='Na entrega/retirada, "2" significa retirada.',
    ),
    TransitionRule(
        current=AwaitingResponse.ENDERECO.value,
        next=AwaitingResponse.NOME_CLIENTE.value,
        matcher=_any_non_empty,
        description="Endereço preenchido leva para coleta do nome.",
    ),
    TransitionRule(
        current=AwaitingResponse.NOME_CLIENTE.value,
        next=AwaitingResponse.FORMA_PAGAMENTO.value,
        matcher=_any_non_empty,
        description="Nome válido leva para forma de pagamento.",
    ),
    TransitionRule(
        current=AwaitingResponse.FORMA_PAGAMENTO.value,
        next=AwaitingResponse.COMPROVANTE.value,
        matcher=_is_exact("1"),
        description='Na forma de pagamento, "1" significa Pix.',
    ),
    TransitionRule(
        current=AwaitingResponse.FORMA_PAGAMENTO.value,
        next=AwaitingResponse.CONFIRMACAO.value,
        matcher=_is_exact("2"),
        description='Na forma de pagamento, "2" significa dinheiro e leva para confirmação.',
    ),
    TransitionRule(
        current=AwaitingResponse.FORMA_PAGAMENTO.value,
        next=AwaitingResponse.CONFIRMACAO.value,
        matcher=_is_exact("3"),
        description='Na forma de pagamento, "3" significa cartão e leva para confirmação.',
    ),
]

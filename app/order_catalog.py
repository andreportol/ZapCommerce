from decimal import Decimal

from app.models import Produto


ORDER_PRODUCT_SPECS = {
    'marmitex_individual': {
        'nome': 'Marmitex individual',
        'people_count': 1,
    },
    'marmita_2_pessoas': {
        'nome': 'Marmita para 2 pessoas',
        'people_count': 2,
    },
    'marmita_3_pessoas': {
        'nome': 'Marmita para 3 pessoas',
        'people_count': 3,
    },
    'marmita_4_pessoas': {
        'nome': 'Marmita para 4 pessoas',
        'people_count': 4,
    },
    'marmita_5_pessoas': {
        'nome': 'Marmita para 5 pessoas',
        'people_count': 5,
    },
}


def format_brl(value: Decimal | float | int) -> str:
    return f'R$ {Decimal(str(value)):.2f}'.replace('.', ',')


def list_order_products(only_available: bool = True) -> list[dict]:
    names = [spec['nome'] for spec in ORDER_PRODUCT_SPECS.values()]
    queryset = Produto.objects.filter(nome__in=names)
    if only_available:
        queryset = queryset.filter(disponivel=True)

    products_by_name = {produto.nome: produto for produto in queryset}
    items = []
    for key, spec in ORDER_PRODUCT_SPECS.items():
        produto = products_by_name.get(spec['nome'])
        if produto is None:
            continue
        items.append(
            {
                'key': key,
                'nome': spec['nome'],
                'people_count': spec['people_count'],
                'produto': produto,
                'preco': float(produto.preco),
                'disponivel': bool(produto.disponivel),
            }
        )
    return items


def get_order_product(product_key: str, only_available: bool = True) -> dict | None:
    for item in list_order_products(only_available=only_available):
        if item['key'] == product_key:
            return item
    return None


def get_order_product_by_people(people_count: int, only_available: bool = True) -> dict | None:
    for item in list_order_products(only_available=only_available):
        if item['people_count'] == people_count:
            return item
    return None


def get_order_product_choices() -> list[dict]:
    choices = []
    for index, item in enumerate(list_order_products(only_available=True), start=1):
        choices.append(
            {
                'choice': str(index),
                'key': item['key'],
                'nome': item['nome'],
                'people_count': item['people_count'],
                'preco': item['preco'],
            }
        )
    return choices

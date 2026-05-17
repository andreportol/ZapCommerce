import logging
import re
from decimal import Decimal

from django.db import transaction

from app.models import Cliente, ConfiguracaoMarmitaria, Conversa, Pedido, Produto

logger = logging.getLogger(__name__)

try:
    from agno.agent import Agent
except Exception:  # pragma: no cover
    Agent = None


def listar_produtos_disponiveis():
    return list(Produto.objects.filter(disponivel=True).order_by('categoria', 'nome'))


def buscar_produto_por_nome(nome):
    nome_limpo = (nome or '').strip()
    if not nome_limpo:
        return None
    produto = Produto.objects.filter(disponivel=True, nome__iexact=nome_limpo).first()
    if produto:
        return produto
    return Produto.objects.filter(disponivel=True, nome__icontains=nome_limpo).first()


def criar_pedido_rascunho(cliente_id, conversa_id):
    pedido = (
        Pedido.objects.filter(cliente_id=cliente_id, conversa_id=conversa_id, status=Pedido.Status.RASCUNHO)
        .order_by('-criado_em')
        .first()
    )
    if pedido:
        return pedido
    return Pedido.objects.create(cliente_id=cliente_id, conversa_id=conversa_id, status=Pedido.Status.RASCUNHO)


def adicionar_item_pedido(pedido_id, produto_id, quantidade):
    pedido = Pedido.objects.get(id=pedido_id)
    produto = Produto.objects.get(id=produto_id)
    item = pedido.itens.filter(produto=produto).first()
    if item:
        item.quantidade += quantidade
        item.preco_unitario = produto.preco
        item.save()
    else:
        item = pedido.itens.create(
            produto=produto,
            quantidade=quantidade,
            preco_unitario=produto.preco,
            subtotal=produto.preco * quantidade,
        )
    calcular_total_pedido(pedido_id)
    return item


def calcular_total_pedido(pedido_id):
    pedido = Pedido.objects.get(id=pedido_id)
    subtotal = sum((item.subtotal for item in pedido.itens.all()), Decimal('0.00'))
    config = ConfiguracaoMarmitaria.objects.filter(ativo=True).first()
    taxa = config.taxa_entrega_padrao if config else Decimal('0.00')
    pedido.subtotal = subtotal
    pedido.taxa_entrega = taxa
    pedido.total = subtotal + taxa
    if not pedido.endereco_entrega and pedido.cliente.endereco:
        pedido.endereco_entrega = pedido.cliente.endereco
    pedido.save(update_fields=['subtotal', 'taxa_entrega', 'total', 'endereco_entrega', 'atualizado_em'])
    return pedido.total


def atualizar_endereco_cliente(cliente_id, endereco, ponto_referencia):
    cliente = Cliente.objects.get(id=cliente_id)
    cliente.endereco = endereco.strip()
    cliente.ponto_referencia = (ponto_referencia or '').strip()
    cliente.save(update_fields=['endereco', 'ponto_referencia', 'atualizado_em'])
    return cliente


def definir_forma_pagamento(pedido_id, forma_pagamento):
    pedido = Pedido.objects.get(id=pedido_id)
    pedido.forma_pagamento = forma_pagamento
    pedido.status = (
        Pedido.Status.AGUARDANDO_PAGAMENTO
        if forma_pagamento == Pedido.FormaPagamento.PIX
        else Pedido.Status.AGUARDANDO_CONFIRMACAO
    )
    pedido.save(update_fields=['forma_pagamento', 'status', 'atualizado_em'])
    return pedido


def confirmar_pedido(pedido_id):
    pedido = Pedido.objects.get(id=pedido_id)
    if pedido.forma_pagamento == Pedido.FormaPagamento.PIX:
        pedido.status = Pedido.Status.AGUARDANDO_PAGAMENTO
    else:
        pedido.status = Pedido.Status.AGUARDANDO_CONFIRMACAO
    pedido.save(update_fields=['status', 'atualizado_em'])
    return pedido


def transferir_para_humano(conversa_id):
    conversa = Conversa.objects.get(id=conversa_id)
    conversa.status = Conversa.Status.HUMANO
    conversa.save(update_fields=['status', 'atualizado_em'])
    return conversa


def _normalizar(texto: str) -> str:
    return re.sub(r'\s+', ' ', (texto or '').strip().lower())


def _extrair_quantidade(texto: str) -> int:
    m = re.search(r'\b(\d{1,2})\b', texto)
    if m:
        return max(1, int(m.group(1)))
    return 1


def _produto_por_texto(texto: str):
    texto_n = _normalizar(texto)
    produtos = listar_produtos_disponiveis()
    for p in produtos:
        if p.nome.lower() in texto_n:
            return p
    for p in produtos:
        if any(token in texto_n for token in p.nome.lower().split()):
            return p
    return None


def _formatar_cardapio(produtos):
    linhas = ['Cardapio de hoje:']
    for p in produtos:
        linhas.append(f'- {p.nome}: R$ {p.preco}')
    return '\n'.join(linhas)


def _resumo_pedido(pedido):
    itens = pedido.itens.all()
    linhas = ['Resumo do pedido:']
    for item in itens:
        linhas.append(f'- {item.quantidade}x {item.produto.nome}: R$ {item.subtotal}')
    linhas.append(f'Subtotal: R$ {pedido.subtotal}')
    linhas.append(f'Taxa de entrega: R$ {pedido.taxa_entrega}')
    linhas.append(f'Total: R$ {pedido.total}')
    return '\n'.join(linhas)


def _resposta_regras(cliente, conversa, texto):
    texto_n = _normalizar(texto)
    config = ConfiguracaoMarmitaria.objects.filter(ativo=True).first()
    boas_vindas = (
        config.mensagem_boas_vindas.strip()
        if config and config.mensagem_boas_vindas.strip()
        else 'Ola! Seja bem-vindo(a) a nossa marmitaria 😊 Posso te mostrar o cardapio de hoje ou voce ja sabe o que deseja pedir?'
    )

    if any(k in texto_n for k in ['humano', 'atendente', 'pessoa', 'falar com alguem']):
        transferir_para_humano(conversa.id)
        return 'Perfeito, vou chamar um atendente para continuar seu atendimento.'

    if not cliente.nome and len(texto_n.split()) <= 5 and any(k in texto_n for k in ['meu nome', 'sou', 'chamo']):
        possivel_nome = texto.strip().split()[-1].title()
        cliente.nome = possivel_nome
        cliente.save(update_fields=['nome', 'atualizado_em'])
        return f'Prazer, {cliente.nome}! Posso te mostrar o cardapio de hoje?'

    if any(k in texto_n for k in ['oi', 'ola', 'bom dia', 'boa tarde', 'boa noite']) and conversa.mensagens.count() <= 2:
        return boas_vindas

    if any(k in texto_n for k in ['cardapio', 'menu', 'opcoes', 'opções']):
        produtos = listar_produtos_disponiveis()
        if not produtos:
            return 'No momento estamos sem produtos disponiveis. Quer que eu chame um atendente humano?'
        return _formatar_cardapio(produtos)

    produto = _produto_por_texto(texto_n)
    if produto:
        qtd = _extrair_quantidade(texto_n)
        with transaction.atomic():
            pedido = criar_pedido_rascunho(cliente.id, conversa.id)
            adicionar_item_pedido(pedido.id, produto.id, qtd)
            pedido.refresh_from_db()
        return (
            f'Adicionei {qtd}x {produto.nome} ao seu pedido.\n'
            f'{_resumo_pedido(pedido)}\n'
            'Deseja adicionar mais algum item?'
        )

    pedido_aberto = (
        Pedido.objects.filter(conversa=conversa)
        .exclude(status__in=[Pedido.Status.ENTREGUE, Pedido.Status.CANCELADO])
        .order_by('-criado_em')
        .first()
    )

    if pedido_aberto and not cliente.endereco and 'rua' in texto_n:
        atualizar_endereco_cliente(cliente.id, texto.strip(), '')
        pedido_aberto.endereco_entrega = cliente.endereco
        pedido_aberto.save(update_fields=['endereco_entrega', 'atualizado_em'])
        return 'Endereco anotado. Qual sera a forma de pagamento? Pix, dinheiro ou cartao na entrega?'

    if pedido_aberto and any(k in texto_n for k in ['pix', 'dinheiro', 'cartao', 'cartão']):
        if 'pix' in texto_n:
            definir_forma_pagamento(pedido_aberto.id, Pedido.FormaPagamento.PIX)
            chave = config.chave_pix if config else ''
            return (
                f'Pagamento via Pix selecionado. Chave Pix: {chave or "nao cadastrada"}.\n'
                'Apos o pagamento, envie o comprovante por aqui para confirmarmos seu pedido.'
            )
        if 'dinheiro' in texto_n:
            definir_forma_pagamento(pedido_aberto.id, Pedido.FormaPagamento.DINHEIRO)
            return 'Pagamento em dinheiro selecionado. Seu pedido ficara aguardando confirmacao e iniciara o preparo em seguida.'

        definir_forma_pagamento(pedido_aberto.id, Pedido.FormaPagamento.CARTAO_ENTREGA)
        return 'Pagamento em cartao na entrega selecionado. Seu pedido ficara aguardando confirmacao.'

    if pedido_aberto and not pedido_aberto.endereco_entrega:
        return 'Para concluir, me informe o endereco de entrega e um ponto de referencia.'

    if pedido_aberto and not pedido_aberto.forma_pagamento:
        return f'{_resumo_pedido(pedido_aberto)}\nQual sera a forma de pagamento? Pix, dinheiro ou cartao na entrega?'

    if pedido_aberto:
        return 'Seu pedido esta registrado e aguardando confirmacao/pagamento. Se quiser, posso chamar um atendente humano.'

    return 'Posso te mostrar o cardapio e te ajudar a montar seu pedido. Deseja ver as opcoes de hoje?'


def responder_com_agente(cliente, conversa, texto):
    historico = list(conversa.mensagens.order_by('-criado_em')[:20][::-1])
    produtos = listar_produtos_disponiveis()
    config = ConfiguracaoMarmitaria.objects.filter(ativo=True).first()

    resposta_regras = _resposta_regras(cliente, conversa, texto)

    if Agent is None:
        return resposta_regras

    try:
        # Mantemos Agno opcional no MVP: o texto final continua governado por regras de negocio.
        _ = Agent(
            name='Atendente Marmitaria',
            instructions=(
                'Voce e atendente humanizado de marmitaria. Seja breve, educado e objetivo. '
                'Nunca invente produtos, precos ou horarios.'
            ),
        )
        return resposta_regras
    except Exception as exc:
        logger.warning('Falha ao inicializar Agno, usando fallback de regras: %s', exc)
        return resposta_regras

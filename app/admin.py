from django.contrib import admin
from django.db import transaction

from .agents.conversation_state import clear_all_states
from .models import Cliente, ConfiguracaoMarmitaria, Conversa, ItemPedido, Mensagem, Pedido, Produto


@admin.action(description='Limpar todo o historico de conversas')
def limpar_todo_historico_conversas(modeladmin, request, queryset):
    """
    Limpa mensagens e estado local sem apagar clientes, conversas ou pedidos.

    Deletar Conversa diretamente apagaria Pedido por cascata, entao esta acao
    limpa apenas o historico de atendimento.
    """
    with transaction.atomic():
        total_mensagens, _ = Mensagem.objects.all().delete()
        total_conversas = Conversa.objects.update(
            status=Conversa.Status.IA,
            ultima_mensagem='',
        )
    clear_all_states()
    modeladmin.message_user(
        request,
        f'Historico limpo: {total_mensagens} mensagens removidas e {total_conversas} conversas resetadas para IA.',
    )


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'telefone', 'endereco', 'criado_em')
    search_fields = ('nome', 'telefone', 'endereco')
    readonly_fields = ('criado_em', 'atualizado_em')


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'categoria', 'preco', 'disponivel', 'atualizado_em')
    search_fields = ('nome', 'descricao')
    list_filter = ('categoria', 'disponivel')
    readonly_fields = ('criado_em', 'atualizado_em')


class MensagemInline(admin.TabularInline):
    model = Mensagem
    extra = 0
    fields = ('origem', 'texto', 'whatsapp_message_id', 'criado_em')
    readonly_fields = ('criado_em',)
    show_change_link = True


@admin.register(Conversa)
class ConversaAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente', 'status', 'ultima_mensagem', 'atualizado_em')
    search_fields = ('cliente__nome', 'cliente__telefone', 'ultima_mensagem')
    list_filter = ('status', 'atualizado_em')
    readonly_fields = ('criado_em', 'atualizado_em')
    inlines = [MensagemInline]
    actions = [limpar_todo_historico_conversas]


class ItemPedidoInline(admin.TabularInline):
    model = ItemPedido
    extra = 0
    fields = ('produto', 'quantidade', 'preco_unitario', 'subtotal')
    readonly_fields = ('subtotal',)


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cliente', 'status', 'forma_pagamento', 'total', 'criado_em')
    search_fields = ('cliente__nome', 'cliente__telefone', 'endereco_entrega')
    list_filter = ('status', 'forma_pagamento', 'criado_em')
    readonly_fields = ('criado_em', 'atualizado_em', 'subtotal', 'total')
    inlines = [ItemPedidoInline]


@admin.register(Mensagem)
class MensagemAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversa', 'origem', 'texto', 'whatsapp_message_id', 'criado_em')
    search_fields = ('texto', 'whatsapp_message_id', 'conversa__cliente__telefone')
    list_filter = ('origem', 'criado_em')
    readonly_fields = ('criado_em',)
    actions = [limpar_todo_historico_conversas]


@admin.register(ConfiguracaoMarmitaria)
class ConfiguracaoMarmitariaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome_empresa', 'telefone_atendimento', 'taxa_entrega_padrao', 'ativo', 'atualizado_em')
    search_fields = ('nome_empresa', 'telefone_atendimento')
    list_filter = ('ativo',)
    readonly_fields = ('criado_em', 'atualizado_em')

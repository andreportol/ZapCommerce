from django.contrib import admin

from .models import Cliente, ConfiguracaoMarmitaria, Conversa, ItemPedido, Mensagem, Pedido, Produto


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


@admin.register(ConfiguracaoMarmitaria)
class ConfiguracaoMarmitariaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome_empresa', 'telefone_atendimento', 'taxa_entrega_padrao', 'ativo', 'atualizado_em')
    search_fields = ('nome_empresa', 'telefone_atendimento')
    list_filter = ('ativo',)
    readonly_fields = ('criado_em', 'atualizado_em')

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class BaseTimestampModel(models.Model):
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Cliente(BaseTimestampModel):
    nome = models.CharField(max_length=150, blank=True)
    telefone = models.CharField(max_length=30, unique=True)
    endereco = models.CharField(max_length=255, blank=True)
    ponto_referencia = models.CharField(max_length=255, blank=True)
    observacoes = models.TextField(blank=True)

    def __str__(self):
        return self.nome or self.telefone


class Produto(BaseTimestampModel):
    class Categoria(models.TextChoices):
        MARMITA_PEQUENA = 'marmita_pequena', 'Marmita pequena'
        MARMITA_MEDIA = 'marmita_media', 'Marmita media'
        MARMITA_GRANDE = 'marmita_grande', 'Marmita grande'
        BEBIDA = 'bebida', 'Bebida'
        ADICIONAL = 'adicional', 'Adicional'
        SOBREMESA = 'sobremesa', 'Sobremesa'

    nome = models.CharField(max_length=120)
    descricao = models.TextField(blank=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    categoria = models.CharField(max_length=30, choices=Categoria.choices)
    disponivel = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} - R$ {self.preco}'


class Conversa(BaseTimestampModel):
    class Status(models.TextChoices):
        IA = 'ia', 'IA'
        HUMANO = 'humano', 'Humano'
        FINALIZADA = 'finalizada', 'Finalizada'

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='conversas')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IA)
    ultima_mensagem = models.TextField(blank=True)

    class Meta:
        ordering = ['-atualizado_em']

    def __str__(self):
        return f'Conversa {self.id} - {self.cliente}'


class Mensagem(models.Model):
    class Origem(models.TextChoices):
        CLIENTE = 'cliente', 'Cliente'
        IA = 'ia', 'IA'
        HUMANO = 'humano', 'Humano'
        SISTEMA = 'sistema', 'Sistema'

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='mensagens')
    origem = models.CharField(max_length=20, choices=Origem.choices)
    texto = models.TextField(blank=True)
    whatsapp_message_id = models.CharField(max_length=120, blank=True, db_index=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em']

    def __str__(self):
        return f'{self.origem} - {self.conversa_id}'


class Pedido(BaseTimestampModel):
    class Status(models.TextChoices):
        RASCUNHO = 'rascunho', 'Rascunho'
        AGUARDANDO_CONFIRMACAO = 'aguardando_confirmacao', 'Aguardando confirmacao'
        AGUARDANDO_PAGAMENTO = 'aguardando_pagamento', 'Aguardando pagamento'
        PAGO = 'pago', 'Pago'
        EM_PREPARO = 'em_preparo', 'Em preparo'
        SAIU_PARA_ENTREGA = 'saiu_para_entrega', 'Saiu para entrega'
        ENTREGUE = 'entregue', 'Entregue'
        CANCELADO = 'cancelado', 'Cancelado'

    class FormaPagamento(models.TextChoices):
        PIX = 'pix', 'Pix'
        DINHEIRO = 'dinheiro', 'Dinheiro'
        CARTAO_ENTREGA = 'cartao_entrega', 'Cartao na entrega'

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='pedidos')
    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='pedidos')
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.RASCUNHO)
    forma_pagamento = models.CharField(max_length=30, choices=FormaPagamento.choices, blank=True)
    endereco_entrega = models.CharField(max_length=255, blank=True)
    observacoes = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    taxa_entrega = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'Pedido {self.id} - {self.cliente}'


class ItemPedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='itens_pedido')
    quantidade = models.PositiveIntegerField()
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    def save(self, *args, **kwargs):
        self.subtotal = (self.preco_unitario or Decimal('0.00')) * self.quantidade
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.quantidade}x {self.produto.nome}'


class ConfiguracaoMarmitaria(BaseTimestampModel):
    nome_empresa = models.CharField(max_length=150)
    telefone_atendimento = models.CharField(max_length=30)
    chave_pix = models.CharField(max_length=120, blank=True)
    horario_funcionamento = models.CharField(max_length=255, blank=True)
    taxa_entrega_padrao = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    mensagem_boas_vindas = models.TextField(blank=True)
    mensagem_fora_horario = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)

    def clean(self):
        if self.ativo:
            qs = ConfiguracaoMarmitaria.objects.filter(ativo=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError('So pode existir uma configuracao ativa.')

    def __str__(self):
        return self.nome_empresa

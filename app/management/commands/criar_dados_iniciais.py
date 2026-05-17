from decimal import Decimal

from django.core.management.base import BaseCommand

from app.models import ConfiguracaoMarmitaria, Produto


class Command(BaseCommand):
    help = 'Cria configuracao inicial e produtos padrao da marmitaria.'

    def handle(self, *args, **options):
        config, created = ConfiguracaoMarmitaria.objects.get_or_create(
            ativo=True,
            defaults={
                'nome_empresa': 'Marmitaria Adriana',
                'telefone_atendimento': '5599999999999',
                'chave_pix': 'pix@exemplo.com',
                'horario_funcionamento': 'Seg a Sab - 10h as 14h',
                'taxa_entrega_padrao': Decimal('5.00'),
                'mensagem_boas_vindas': 'Ola! Seja bem-vindo(a) a nossa marmitaria 😊 Posso te mostrar o cardapio de hoje ou voce ja sabe o que deseja pedir?',
                'mensagem_fora_horario': 'Estamos fora do horario de atendimento no momento.',
            },
        )
        self.stdout.write(self.style.SUCCESS('Configuracao criada.' if created else 'Configuracao ja existia.'))

        produtos = [
            ('Marmita pequena', 'Marmita pequena tradicional', Decimal('18.00'), Produto.Categoria.MARMITA_PEQUENA),
            ('Marmita media', 'Marmita media tradicional', Decimal('22.00'), Produto.Categoria.MARMITA_MEDIA),
            ('Marmita grande', 'Marmita grande tradicional', Decimal('27.00'), Produto.Categoria.MARMITA_GRANDE),
            ('Refrigerante lata', 'Lata 350ml', Decimal('6.00'), Produto.Categoria.BEBIDA),
            ('Agua mineral', 'Garrafa 500ml', Decimal('4.00'), Produto.Categoria.BEBIDA),
            ('Ovo adicional', 'Unidade', Decimal('2.50'), Produto.Categoria.ADICIONAL),
            ('Sobremesa do dia', 'Consultar disponibilidade', Decimal('7.00'), Produto.Categoria.SOBREMESA),
        ]

        for nome, descricao, preco, categoria in produtos:
            Produto.objects.get_or_create(
                nome=nome,
                defaults={
                    'descricao': descricao,
                    'preco': preco,
                    'categoria': categoria,
                    'disponivel': True,
                },
            )

        self.stdout.write(self.style.SUCCESS('Produtos iniciais criados/garantidos.'))

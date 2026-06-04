from datetime import time
from decimal import Decimal

from django.core.management.base import BaseCommand

from app.models import CardapioDia, ConfiguracaoMarmitaria, DiaSemana, HorarioFuncionamentoDia, Produto


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
                'aceita_pedidos': True,
                'aceita_entrega': True,
                'aceita_retirada_local': True,
                'pedido_maximo_sem_consulta': 5,
                'endereco_retirada': 'Balcao da marmitaria',
                'mensagem_boas_vindas': 'Ola! Seja bem-vindo(a) a nossa marmitaria 😊 Posso te mostrar o cardapio de hoje ou voce ja sabe o que deseja pedir?',
                'mensagem_fora_horario': 'Estamos fora do horario de atendimento no momento.',
            },
        )
        self.stdout.write(self.style.SUCCESS('Configuracao criada.' if created else 'Configuracao ja existia.'))

        horarios = {
            DiaSemana.SEGUNDA: ['Feijoada da casa', 'Arroz branco', 'Farofa', 'Couve refogada'],
            DiaSemana.TERCA: ['Frango assado', 'Arroz', 'Feijão carioca', 'Macarrão alho e óleo'],
            DiaSemana.QUARTA: ['Bife acebolado', 'Arroz', 'Feijão tropeiro', 'Purê de batata'],
            DiaSemana.QUINTA: ['Strogonoff de frango', 'Arroz', 'Batata palha', 'Salada'],
            DiaSemana.SEXTA: ['Peixe empanado', 'Arroz', 'Purê', 'Legumes'],
            DiaSemana.SABADO: ['Costela assada', 'Arroz', 'Mandioca cozida', 'Vinagrete'],
        }

        for dia_semana, itens in horarios.items():
            HorarioFuncionamentoDia.objects.update_or_create(
                configuracao=config,
                dia_semana=dia_semana,
                defaults={
                    'fechado': False,
                    'abre_pedidos': time(9, 0),
                    'fecha_pedidos': time(12, 30),
                    'abre_entregas': time(11, 0),
                    'fecha_entregas': time(13, 0),
                    'abre_retiradas': time(11, 0),
                    'fecha_retiradas': time(13, 0),
                    'observacoes': '',
                },
            )
            CardapioDia.objects.update_or_create(
                configuracao=config,
                dia_semana=dia_semana,
                defaults={
                    'titulo': f'Cardapio de {dia_semana}',
                    'descricao': '\n'.join(f'- {item}' for item in itens),
                    'ativo': True,
                },
            )

        HorarioFuncionamentoDia.objects.update_or_create(
            configuracao=config,
            dia_semana=DiaSemana.DOMINGO,
            defaults={
                'fechado': True,
                'abre_pedidos': None,
                'fecha_pedidos': None,
                'abre_entregas': None,
                'fecha_entregas': None,
                'abre_retiradas': None,
                'fecha_retiradas': None,
                'observacoes': 'Fechado',
            },
        )

        produtos = [
            ('Marmitex individual', 'Opcao individual', Decimal('21.00'), Produto.Categoria.MARMITA_PEQUENA),
            ('Marmita para 2 pessoas', 'Opcao para 2 pessoas', Decimal('65.00'), Produto.Categoria.MARMITA_MEDIA),
            ('Marmita para 3 pessoas', 'Opcao para 3 pessoas', Decimal('85.00'), Produto.Categoria.MARMITA_MEDIA),
            ('Marmita para 4 pessoas', 'Opcao para 4 pessoas', Decimal('105.00'), Produto.Categoria.MARMITA_GRANDE),
            ('Marmita para 5 pessoas', 'Opcao para 5 pessoas', Decimal('125.00'), Produto.Categoria.MARMITA_GRANDE),
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
        self.stdout.write(self.style.SUCCESS('Horarios e cardapios iniciais criados/garantidos.'))

from decimal import Decimal

from django.db import migrations


def seed_order_products(apps, schema_editor):
    Produto = apps.get_model('app', 'Produto')

    products = [
        ('Marmitex individual', 'Opcao individual', Decimal('21.00'), 'marmita_pequena'),
        ('Marmita para 2 pessoas', 'Opcao para 2 pessoas', Decimal('65.00'), 'marmita_media'),
        ('Marmita para 3 pessoas', 'Opcao para 3 pessoas', Decimal('85.00'), 'marmita_media'),
        ('Marmita para 4 pessoas', 'Opcao para 4 pessoas', Decimal('105.00'), 'marmita_grande'),
        ('Marmita para 5 pessoas', 'Opcao para 5 pessoas', Decimal('125.00'), 'marmita_grande'),
    ]

    for nome, descricao, preco, categoria in products:
        Produto.objects.get_or_create(
            nome=nome,
            defaults={
                'descricao': descricao,
                'preco': preco,
                'categoria': categoria,
                'disponivel': True,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0002_estadoconversa'),
    ]

    operations = [
        migrations.RunPython(seed_order_products, migrations.RunPython.noop),
    ]

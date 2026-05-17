# Instruções para o Codex

Este é um projeto Django para atendimento de uma marmitaria via WhatsApp com IA.

## Regras gerais

- Não expor tokens, senhas ou chaves de API.
- Usar variáveis de ambiente para integrações externas.
- Não executar comandos destrutivos no banco de dados.
- Antes de alterar arquivos, explicar o plano.
- Não remover migrations antigas.
- Usar PostgreSQL como banco principal.
- Toda integração com WhatsApp deve ficar centralizada em um service próprio.
- Separar ambiente de teste e produção.

## Comandos úteis

python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
python manage.py test

## Objetivo do projeto

- Receber mensagens via WhatsApp.
- Identificar clientes.
- Interpretar pedidos com IA.
- Registrar pedidos no banco.
- Confirmar pagamento.
- Criar dashboard com dados no PostgreSQL.
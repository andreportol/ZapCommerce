# marmitaria_ia (MVP)

MVP para atendimento de marmitaria via WhatsApp Cloud API com automacao por IA e painel via Django Admin.

## Como rodar

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py criar_dados_iniciais
python manage.py runserver
```

## Rotas

- `/admin/`
- `/api/whatsapp/webhook/`
- `/health/`

## Configuracao do webhook na Meta

- URL: `https://meu-dominio.com/api/whatsapp/webhook/`
- Verify Token: valor de `WHATSAPP_VERIFY_TOKEN`

## Arquivos de ambiente

- `.env.example`: base para desenvolvimento local.
- `.env.test.example`: exemplo para ambiente de testes.
- `.env.production.example`: exemplo para producao.

## Publicacao no GitHub

1. Inicialize o repositório local:
```bash
git init
git add .
git commit -m "chore: inicializa projeto django marmitaria"
```
2. Crie o repositório no GitHub e conecte o remoto:
```bash
git branch -M main
git remote add origin https://github.com/<seu-usuario>/<seu-repo>.git
git push -u origin main
```
3. Nunca versione `.env`; use apenas `.env.example` para compartilhar estrutura de variaveis.

## Observacoes

- O MVP processa webhook de forma sincrona. Em producao, usar Celery + Redis.
- Estrutura preparada para evoluir suporte a midia (audio/imagem/documento) no webhook.

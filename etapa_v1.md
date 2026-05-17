# etapa_v1 - Status do MVP Marmitaria IA

## 1. Objetivo do projeto
Foi criado um MVP Django para uma marmitaria unica (nao SaaS), com atendimento automatizado via WhatsApp Cloud API, persistencia no PostgreSQL e operacao principal via Django Admin.

## 2. Stack implementada
- Python
- Django 5.2.13
- Django Admin
- PostgreSQL (via `DATABASE_URL`)
- Agno (estrutura de agente criada)
- WhatsApp Cloud API (envio com `requests`)
- `python-decouple` para variaveis de ambiente
- `dj-database-url`
- WhiteNoise / Gunicorn preparados (deploy futuro)

## 3. Estrutura criada
- Projeto Django: `marmitaria_ia`
- App principal: `app`
- Pastas/arquivos relevantes:
  - `app/models.py`
  - `app/admin.py`
  - `app/views.py`
  - `app/services.py`
  - `app/agents/marmitaria_agent.py`
  - `app/management/commands/criar_dados_iniciais.py`
  - `marmitaria_ia/settings.py`
  - `marmitaria_ia/urls.py`
  - `.env.example`
  - `requirements.txt`
  - `Procfile`

## 4. Models implementados
### Cliente
- `nome`
- `telefone` (unico)
- `endereco`
- `ponto_referencia`
- `observacoes`
- `criado_em`, `atualizado_em`

### Produto
- `nome`
- `descricao`
- `preco`
- `categoria` (`marmita_pequena`, `marmita_media`, `marmita_grande`, `bebida`, `adicional`, `sobremesa`)
- `disponivel`
- `criado_em`, `atualizado_em`

### Conversa
- `cliente`
- `status` (`ia`, `humano`, `finalizada`)
- `ultima_mensagem`
- `criado_em`, `atualizado_em`

### Mensagem
- `conversa`
- `origem` (`cliente`, `ia`, `humano`, `sistema`)
- `texto`
- `whatsapp_message_id`
- `criado_em`

### Pedido
- `cliente`
- `conversa`
- `status` (`rascunho`, `aguardando_confirmacao`, `aguardando_pagamento`, `pago`, `em_preparo`, `saiu_para_entrega`, `entregue`, `cancelado`)
- `forma_pagamento` (`pix`, `dinheiro`, `cartao_entrega`)
- `endereco_entrega`
- `observacoes`
- `subtotal`
- `taxa_entrega`
- `total`
- `criado_em`, `atualizado_em`

### ItemPedido
- `pedido`
- `produto`
- `quantidade`
- `preco_unitario`
- `subtotal` (calculado no `save`)

### ConfiguracaoMarmitaria
- `nome_empresa`
- `telefone_atendimento`
- `chave_pix`
- `horario_funcionamento`
- `taxa_entrega_padrao`
- `mensagem_boas_vindas`
- `mensagem_fora_horario`
- `ativo`
- `criado_em`, `atualizado_em`
- validacao para manter somente uma configuracao ativa

## 5. Webhook WhatsApp implementado
### Endpoint unico
- `GET /api/whatsapp/webhook/`
  - valida `hub.verify_token` contra `WHATSAPP_VERIFY_TOKEN`
  - retorna `hub.challenge` em texto puro
- `POST /api/whatsapp/webhook/`
  - processa payload da Meta
  - extrai telefone, mensagem e id
  - cria/recupera cliente automaticamente
  - cria/recupera conversa ativa
  - salva mensagem de entrada
  - chama agente
  - salva resposta da IA
  - envia resposta para WhatsApp Cloud API
  - retorna `{"status": "ok"}`

### Resiliencia implementada
- nao quebra quando vier payload sem `messages` (status de entrega/leitura)
- ignora mensagem sem texto (preparado para evoluir midia depois)
- captura excecoes com log

## 6. Servicos implementados (`app/services.py`)
- `obter_configuracao_ativa`
- `criar_ou_obter_cliente_por_telefone`
- `obter_ou_criar_conversa_ativa`
- `salvar_mensagem`
- `enviar_mensagem_whatsapp(telefone, texto)`
- `obter_historico`
- `processar_mensagem_whatsapp(payload)`

Observacao no codigo: hoje sincrono; em producao ideal usar Celery + Redis.

## 7. Agente IA implementado (`app/agents/marmitaria_agent.py`)
### Ferramentas/funcoes criadas
- `listar_produtos_disponiveis()`
- `buscar_produto_por_nome(nome)`
- `criar_pedido_rascunho(cliente_id, conversa_id)`
- `adicionar_item_pedido(pedido_id, produto_id, quantidade)`
- `calcular_total_pedido(pedido_id)`
- `atualizar_endereco_cliente(cliente_id, endereco, ponto_referencia)`
- `definir_forma_pagamento(pedido_id, forma_pagamento)`
- `confirmar_pedido(pedido_id)`
- `transferir_para_humano(conversa_id)`
- `responder_com_agente(cliente, conversa, texto)`

### Comportamento atual
- saudacao inicial
- mostra cardapio com produtos disponiveis
- identifica produto pelo texto e adiciona item no pedido
- calcula subtotal/taxa/total
- solicita endereco quando necessario
- solicita forma de pagamento
- se Pix, envia chave Pix da configuracao
- se cliente pedir humano, muda `conversa.status` para `humano`
- se conversa em humano, webhook nao responde com IA automaticamente

### Nota sobre Agno
- Agno foi integrado de forma segura/opcional.
- Se Agno falhar/indisponivel, fallback para regras de negocio locais.
- O texto final atual e governado por regras deterministicas para evitar alucinacao e inventar produtos/precos.

## 8. Admin configurado
Todos os models registrados com:
- `list_display`
- `search_fields`
- `list_filter`
- `readonly_fields` para datas
- inline de `ItemPedido` dentro de `Pedido`
- inline de `Mensagem` dentro de `Conversa`

## 9. Rotas ativas
- `/` -> `home_view` (JSON simples para confirmar app online)
- `/admin/`
- `/health/` -> `{"status": "ok"}`
- `/api/whatsapp/webhook/`

## 10. Configuracao de ambiente
### `.env.example` criado com:
- `SECRET_KEY`
- `DEBUG`
- `DATABASE_URL`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_API_VERSION`
- `OPENAI_API_KEY`

### Ajuste importante realizado
Foi corrigido o `settings.py` para evitar erro `UnknownSchemeError` quando `DATABASE_URL` vier vazia.
- agora so usa `dj_database_url.parse` se `DATABASE_URL` tiver valor
- fallback para sqlite local se estiver vazia

## 11. Banco e migracoes
- migracao inicial criada: `app/migrations/0001_initial.py`
- `python manage.py check` sem erros

## 12. Dados iniciais
Comando implementado:
- `python manage.py criar_dados_iniciais`

Cria/garante:
- 1 `ConfiguracaoMarmitaria` ativa
- produtos iniciais:
  - Marmita pequena
  - Marmita media
  - Marmita grande
  - Refrigerante lata
  - Agua mineral
  - Ovo adicional
  - Sobremesa do dia

## 13. Arquivos operacionais
- `requirements.txt` com dependencias do MVP
- `Procfile` criado para deploy futuro (Railway/Heroku style)
- `README.md` com instrucoes basicas

## 14. Fluxo atual funcionando
1. Cliente manda mensagem no WhatsApp
2. Webhook recebe
3. Sistema salva cliente/conversa/mensagem
4. Agente responde com cardapio e conduz pedido
5. Sistema monta pedido e calcula total
6. Sistema pergunta pagamento e informa Pix quando aplicavel
7. Tudo pode ser acompanhado no Django Admin

## 15. Pendencias/evolucoes recomendadas (proxima etapa)
- trocar processamento sincrono do webhook por Celery + Redis
- melhorar NLP para extrair endereco/ponto de referencia com mais confianca
- suportar midia (audio/imagem/documento) do WhatsApp
- confirmar comprovante Pix e transicao automatica de status do pedido
- cobertura de testes automatizados (models/services/webhook)
- controle de horario de funcionamento com resposta fora de horario

## 16. Como rodar localmente (Windows/PostgreSQL)
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py criar_dados_iniciais
python manage.py runserver
```

Para webhook real com Meta (local): usar ngrok e cadastrar:
- Callback URL: `https://SEU_DOMINIO_NGROK/api/whatsapp/webhook/`
- Verify Token: valor de `WHATSAPP_VERIFY_TOKEN`

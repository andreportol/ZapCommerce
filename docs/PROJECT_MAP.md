# Project Map

## Visão Geral

`Marmitaria_Adriana` é um projeto Django para atendimento de pedidos via WhatsApp com apoio de IA. O projeto hoje concentra a operação em um único app Django chamado `app`, enquanto o pacote `marmitaria_ia` cuida da configuração global do projeto.

O fluxo principal atual é:

1. webhook do WhatsApp recebe a mensagem
2. `app/services.py` normaliza a entrada, salva histórico e chama o orquestrador
3. `app/agents/orchestrator_agent.py` decide a rota da conversa
4. `app/agents/order_agent.py` executa a lógica de pedido
5. estado da conversa é lido e salvo em `app/agents/conversation_state.py`
6. pedido e itens são persistidos em `Pedido` e `ItemPedido`

## Estrutura de Pastas

```text
app/
  agents/                 # agentes conversacionais e helpers de IA
  management/commands/    # comandos de apoio e simulação
  migrations/             # histórico de migrations
  tests/                  # testes automatizados
  admin.py                # configuração do Django Admin
  business_config.py      # regras de horário e configuração operacional
  forms.py                # autenticação do dashboard
  models.py               # modelos principais
  order_catalog.py        # catálogo dos produtos principais e formatação de preço
  services.py             # entrada principal do WhatsApp e envio de mensagens
  tasks.py                # task Celery de debug
  views.py                # webhook, healthcheck, landing e dashboard

marmitaria_ia/
  settings.py             # settings Django
  urls.py                 # rotas principais
  asgi.py / wsgi.py       # entradas ASGI/WSGI
  celery.py               # bootstrap do Celery

templates/
  landing/                # página pública
  dashboard/              # dashboard operacional
  registration/           # login

static/
  app/css/                # estilos da landing, dashboard e auth
  app/img/                # assets visuais

docs/
  *.md                    # documentação técnica e skills internas
```

## Organização Lógica Oficial

Mesmo que o projeto hoje ainda esteja concentrado em `app/`, a organização lógica oficial para leitura e evolução da base passa a ser esta:

- `agents/`
  Responsáveis por interpretar mensagens e decidir o próximo passo.
- `services/`
  Responsáveis pelas regras de negócio e coordenação operacional.
- `conversation/`
  Responsável por estados, transições e fluxo.
- `integrations/`
  Responsável por WhatsApp, Meta, e-mail, Asaas e APIs externas.
- `repositories/`
  Responsável por acesso a dados quando o projeto crescer.
- `tests/`
  Responsável por validar fluxos completos.

Essa organização é, neste momento, uma convenção arquitetural e de responsabilidade. Ela não significa que os diretórios físicos já existam com essa separação.

## Mapeamento da Estrutura Atual Para a Organização Lógica

- `agents/`
  Equivale hoje principalmente a `app/agents/`.
- `services/`
  Equivale hoje principalmente a `app/services.py`, partes de `app/business_config.py` e regras operacionais em `app/views.py`.
- `conversation/`
  Equivale hoje principalmente a `app/agents/conversation_state.py`, além de transições espalhadas entre `orchestrator_agent.py` e `order_agent.py`.
- `integrations/`
  Equivale hoje principalmente à integração WhatsApp centralizada em `app/services.py`.
- `repositories/`
  Ainda não existe como camada dedicada. O acesso a dados hoje ocorre diretamente via ORM Django em `services.py`, `conversation_state.py`, `business_config.py`, `views.py` e agentes.
- `tests/`
  Equivale hoje principalmente a `app/tests/` e aos comandos de simulação em `app/management/commands/`.

## Principais Arquivos

- `app/services.py`
  Responsável por processar o webhook, salvar mensagens, decidir quando encaminhar para humano e centralizar o envio de mensagem pelo WhatsApp Cloud API.
- `app/agents/orchestrator_agent.py`
  Camada principal de orquestração. Decide se a mensagem vai para fluxo de pedido, cardápio, informações operacionais, pagamento, retomada, recuperação ou fallback.
- `app/agents/order_agent.py`
  Regra central do pedido. Monta itens, calcula total, oferece complementos, coleta entrega/retirada, nome, pagamento e comprovante.
- `app/agents/conversation_state.py`
  Estado persistente da conversa. Faz leitura, atualização, reset e saneamento de contexto entre mensagens.
- `app/agents/message_agent.py`
  Extração de intenção e sinais estruturados da mensagem do cliente.
- `app/agents/payment_proof_agent.py`
  Detecta se houve envio de comprovante. Não confirma pagamento automaticamente.
- `app/business_config.py`
  Regras de horário, janelas de pedido, entrega e retirada, mensagens dinâmicas do negócio e limite para consulta da proprietária.
- `app/order_catalog.py`
  Catálogo dos produtos principais de marmita e marmitex. Também fornece helpers de formatação e listagem.
- `app/models.py`
  Modelos de cliente, conversa, estado, pedido, item de pedido, produto, configuração e cardápio.
- `app/views.py`
  Webhook do WhatsApp, healthcheck, landing page e dashboard operacional.
- `app/tests/test_cardapio_day_context.py`
  Principal suíte automatizada atual para fluxos de conversa, pedido, horários, pagamento, cardápio, retomada e resiliência.

## Principais Agentes e Responsabilidades

- `OrchestratorAgent`
  Orquestra o atendimento ponta a ponta.
- `OrderAgent`
  Controla pedido, itens, totais, complementos e progresso da compra.
- `MessageAgent`
  Faz classificação rápida de intenção e extração de campos estruturados.
- `PaymentProofAgent`
  Detecta comprovante enviado para conferência manual.
- `CardapioAgent`
  Lê o cardápio atual a partir da configuração ativa ou de `cardapio.txt`.
- `InstructionsAgent`
  Monta instruções textuais para contexto de atendimento com dados dinâmicos do negócio.
- `DatabaseAgent`
  Placeholder para consultas futuras de status/pagamento em banco.
- `FileAgent`
  Lê metadados simples de arquivo recebido.
- `RagAgent`
  Apoio para recuperação de trechos relevantes de conhecimento textual.

## Onde Fica Cada Regra Principal

- Regras de pedido:
  `app/agents/order_agent.py`
- Estados da conversa:
  `app/agents/conversation_state.py`
- Fluxo de pagamento:
  `app/agents/order_agent.py`
- Tratamento de comprovante:
  `app/agents/payment_proof_agent.py` e etapa correspondente em `app/agents/order_agent.py`
- Horário de atendimento e bloqueios fora do horário:
  `app/business_config.py` e uso em `app/agents/orchestrator_agent.py`
- Integração WhatsApp:
  `app/services.py`
- Produtos principais e preços base:
  `app/order_catalog.py`
- Dashboard operacional:
  `app/views.py` e `templates/dashboard/home.html`
- Testes existentes:
  `app/tests/` e comandos de simulação em `app/management/commands/`

## Pontos de Atenção

- O sistema usa um único app Django principal. Mudanças em `app/agents/order_agent.py` costumam ter alto impacto funcional.
- A organização lógica desejada já está definida, mas a estrutura física ainda não foi separada por camadas. Em mudanças futuras, usar essa convenção para decidir responsabilidades antes de criar novos arquivos.
- O estado da conversa é persistido no banco via `EstadoConversa`. Qualquer novo passo conversacional precisa ser refletido em `status_atendimento` e `aguardando_resposta`.
- O fluxo de pedido e pagamento depende de validações em cadeia no `OrderAgent`; mudanças pequenas podem afetar retomada de conversa e confirmação final.
- O orquestrador possui rotas de fallback e recuperação. Não remover esses caminhos sem substituir a proteção.
- A integração com WhatsApp deve continuar centralizada em `app/services.py`.
- `DatabaseAgent` ainda é um stub. Não assumir que consultas de status/pagamento já existem.
- O bloqueio fora do horário depende de `business_config.py` e de verificações no orquestrador. Não duplicar essa regra em múltiplos pontos sem necessidade.
- Quando o projeto crescer, novas integrações e novas regras de acesso a dados devem preferencialmente nascer já alinhadas às áreas lógicas `integrations/` e `repositories/`.

## Testes Existentes

- `app/tests/test_cardapio_day_context.py`
  Cobre menu, cardápio, pedido, complementos, entrega, retirada, nome, pagamento, Pix, comprovante, retomada, recuperação e horários.
- `app/management/commands/testar_*.py`
  Utilitários manuais para simulação de cenários de intenção e conversa.

## Comandos Úteis

```bash
python manage.py check
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
python manage.py test
python manage.py test app.tests.test_cardapio_day_context
python manage.py criar_dados_iniciais
```

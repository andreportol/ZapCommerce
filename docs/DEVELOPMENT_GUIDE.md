# Development Guide

## Papel Deste Documento

Este é o documento central do projeto. Sempre que houver alteração relevante, ele deve ser revisado junto com:

1. `docs/PROJECT_MAP.md`
2. a skill relacionada em `docs/skills/`
3. `docs/CONVERSATION_FLOW.md`
4. `docs/STATE_MACHINE.md`
5. `docs/CONTRACTS.md`
6. `docs/TEST_STRATEGY.md`
7. `docs/CHANGELOG_IA.md`

## Visão Geral da Arquitetura

O projeto usa Django como base, com um único app principal chamado `app`. A entrada operacional chega pelo webhook do WhatsApp em `app/views.py`, é processada por `app/services.py` e depois roteada para os agentes do diretório `app/agents/`.

Arquitetura funcional atual:

1. entrada HTTP no webhook
2. persistência de cliente, conversa e mensagem
3. orquestração da intenção da conversa
4. execução do fluxo específico de pedido, cardápio, informação operacional ou comprovante
5. resposta final enviada ao WhatsApp

## Organização Lógica Que Deve Guiar Novas Alterações

Mesmo sem refatoração física imediata, o projeto deve ser pensado com esta divisão de responsabilidades:

- `agents/`
  Interpretam mensagens e decidem o próximo passo.
- `services/`
  Implementam regras de negócio e coordenação operacional.
- `conversation/`
  Mantêm estados, transições e fluxo da conversa.
- `integrations/`
  Agrupam WhatsApp, Meta, Asaas, e-mail e APIs externas.
- `repositories/`
  Devem concentrar acesso a dados quando a base crescer.
- `tests/`
  Validam fluxos completos e regressões.

## Mapeamento Atual Para Essa Organização

- `agents/`
  Hoje está concentrado em `app/agents/`.
- `services/`
  Hoje está concentrado em `app/services.py` e partes de `app/business_config.py`.
- `conversation/`
  Hoje está concentrado em `app/agents/conversation_state.py` e em transições distribuídas nos agentes.
- `integrations/`
  Hoje está concentrado na integração WhatsApp em `app/services.py`.
- `repositories/`
  Ainda não existe como camada dedicada; o ORM é usado diretamente.
- `tests/`
  Hoje está concentrado em `app/tests/`.

## Agentes e Responsabilidades

- `OrchestratorAgent`
  Coordena o atendimento e escolhe a próxima ação.
- `OrderAgent`
  Implementa o fluxo oficial do pedido.
- `MessageAgent`
  Extrai intenção, quantidade, tipo de entrega e outros sinais.
- `PaymentProofAgent`
  Identifica comprovante para conferência manual.
- `CardapioAgent`
  Fornece o cardápio do dia/semana.
- `InstructionsAgent`
  Injeta contexto dinâmico do negócio.
- `DatabaseAgent`
  Estrutura futura para consultas.
- `FileAgent`
  Lê metadados simples de anexos.
- `RagAgent`
  Recupera conhecimento textual de apoio.

## Fluxo Oficial do Pedido

O fluxo oficial atual é:

1. cliente inicia pedido
2. seleção do produto principal
3. definição da quantidade
4. resumo parcial
5. oferta de complementos válidos
6. decisão de adicionar mais complementos ou seguir
7. entrega ou retirada
8. coleta de endereço quando necessário
9. coleta do nome do cliente
10. escolha da forma de pagamento
11. instruções Pix quando aplicável
12. recebimento do comprovante quando aplicável
13. conferência manual do comprovante
14. confirmação final do pedido

## Estados Principais da Conversa

Estados e esperas principais hoje:

- `inicio`
- `fazendo_pedido`
- `aguardando_produto`
- `aguardando_quantidade`
- `aguardando_pessoas_marmita`
- `aguardando_tipo_entrega`
- `aguardando_endereco`
- `aguardando_nome_cliente`
- `aguardando_pagamento`
- `aguardando_comprovante`
- `aguardando_conferencia_pagamento`
- `aguardando_confirmacao`
- `aguardando_confirmacao_item`

Esperas importantes em `aguardando_resposta`:

- `produto`
- `tipo_marmita`
- `quantidade`
- `complemento`
- `quantidade_complemento`
- `mais_complementos`
- `tipo_entrega`
- `endereco`
- `nome_cliente`
- `forma_pagamento`
- `comprovante`
- `confirmacao`

## Regras de Negócio

- PostgreSQL é o banco principal.
- Não expor tokens, segredos ou chaves de API.
- Não executar comandos destrutivos no banco.
- Não remover migrations antigas.
- Integração WhatsApp deve permanecer centralizada em `app/services.py`.
- Fluxo de pagamento não deve confirmar Pix automaticamente.
- Pedidos acima do limite configurado exigem consulta da proprietária.
- Horários de pedido, entrega e retirada vêm de `app/business_config.py`.
- Produtos principais devem continuar sendo controlados por `app/order_catalog.py`.

## Regras de Segurança Para Alterações

- Não refatorar arquivos inteiros sem necessidade real.
- Alterar somente o trecho necessário.
- Não mudar `models.py` nesta trilha sem justificativa explícita.
- Não criar migration em tarefas de documentação, teste ou ajuste localizado de conversa.
- Não alterar preços existentes em tarefas que não pedem revisão comercial.
- Não quebrar o fluxo de fallback e recuperação do orquestrador.
- Não espalhar lógica de WhatsApp fora de `app/services.py`.
- Usar a organização lógica oficial para escolher o lugar correto de novas responsabilidades, mesmo que a pasta física ainda não exista.
- As skills do projeto devem sempre respeitar a arquitetura lógica oficial.
- Novas responsabilidades devem nascer no local conceitual correto antes de nascer em um novo arquivo físico.
- Se a pasta física ainda não existir, documentar a intenção primeiro e só depois criar a estrutura em etapa separada.
- Refatorações arquiteturais devem ser feitas em etapas pequenas, com cobertura de testes antes da migração seguinte.

## Como Validar Mudanças

Checklist mínimo de validação:

1. rodar `python manage.py check`
2. rodar testes específicos do fluxo alterado
3. confirmar que o estado da conversa segue consistente
4. revisar mensagens finais ao cliente
5. atualizar `docs/CHANGELOG_IA.md`

## Comandos de Teste

```bash
python manage.py check
python manage.py test
python manage.py test app.tests.test_cardapio_day_context
python manage.py testar_conversa_completa
python manage.py testar_orchestrator_intencoes
python manage.py testar_order_structured
```

## Checklist Antes de Alterar Código

1. consultar `docs/PROJECT_MAP.md`
2. consultar a skill relacionada em `docs/skills/`
3. consultar `docs/CONVERSATION_FLOW.md`
4. consultar `docs/STATE_MACHINE.md` se a mudança afetar estado ou transição
5. consultar `docs/CONTRACTS.md` se a mudança afetar retornos de agentes
6. consultar `docs/TEST_STRATEGY.md` para definir a validação mínima
7. identificar em qual área lógica a mudança pertence: `agents`, `services`, `conversation`, `integrations`, `repositories` ou `tests`
8. localizar os testes atuais do fluxo afetado
9. alterar somente o necessário
10. decidir antes se a mudança afeta estado, mensagens ou persistência
11. se a pasta física correta ainda não existir, registrar a intenção documental antes de propor criação estrutural

## Checklist Depois de Alterar Código

1. revisar diff para garantir escopo pequeno
2. atualizar ou criar testes
3. rodar validações mínimas
4. atualizar `docs/CHANGELOG_IA.md`
5. revisar se `DEVELOPMENT_GUIDE.md`, `PROJECT_MAP.md` ou `CONVERSATION_FLOW.md` precisam ajuste

## Regra Obrigatória Para Mudanças Futuras

Antes de qualquer alteração futura, o Codex deve:

1. consultar `PROJECT_MAP.md`
2. consultar a skill relacionada
3. consultar `CONVERSATION_FLOW.md`
4. consultar `STATE_MACHINE.md` quando houver impacto em estados
5. consultar `CONTRACTS.md` quando houver impacto em retornos estruturados
6. consultar `TEST_STRATEGY.md` para cobrir a alteração
7. alterar somente o necessário
8. atualizar testes
9. atualizar `CHANGELOG_IA.md`

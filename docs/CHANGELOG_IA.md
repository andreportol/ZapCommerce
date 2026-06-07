# Changelog IA

## 2026-06-06 - Complementos Antes de Entrega/Retirada

- Objetivo:
  Inserir a etapa de complementos entre o pedido principal e a escolha de entrega/retirada.
- Arquivos alterados:
  `app/agents/order_agent.py`
  `app/agents/orchestrator_agent.py`
  `app/agents/message_agent.py`
  `app/tests/test_cardapio_day_context.py`
- Resumo da mudança:
  Adicionada oferta de complementos ativos, controle de quantidade de complementos, recálculo do total e continuação para entrega/retirada somente após essa etapa.
- Testes executados:
  `python3 manage.py test app.tests.test_cardapio_day_context`
  `python3 manage.py check`
- Riscos ou observações:
  O fluxo depende dos produtos ativos e com preço válido no banco para a lista automática de complementos.

## 2026-06-06 - Validação de Complementos Sem Preço

- Objetivo:
  Garantir que itens ativos sem preço, como `Sobremesa do dia`, não quebrem o fluxo e não entrem com valor nulo.
- Arquivos alterados:
  `app/tests/test_cardapio_day_context.py`
- Resumo da mudança:
  Adicionado teste para confirmar que itens ativos sem preço não aparecem na lista automática de complementos.
- Testes executados:
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  A regra atual escolhida é ocultar itens sem preço da lista automática.

## 2026-06-06 - Documentação Técnica e Skills Internas

- Objetivo:
  Mapear o projeto atual e criar documentação operacional para facilitar futuras alterações.
- Arquivos alterados:
  `docs/PROJECT_MAP.md`
  `docs/DEVELOPMENT_GUIDE.md`
  `docs/CONVERSATION_FLOW.md`
  `docs/CHANGELOG_IA.md`
  `docs/skills/01_ajustar_fluxo_conversacional.md`
  `docs/skills/02_ajustar_estados_conversa.md`
  `docs/skills/03_ajustar_pedidos_itens.md`
  `docs/skills/04_ajustar_cardapio_estoque.md`
  `docs/skills/05_ajustar_pagamento_comprovante.md`
  `docs/skills/06_ajustar_horarios.md`
  `docs/skills/07_criar_testes_conversa.md`
  `docs/skills/08_revisar_mensagens_whatsapp.md`
- Resumo da mudança:
  Criado mapa técnico do projeto, guia central de desenvolvimento, fluxo conversacional oficial e conjunto de skills internas para manutenção orientada.
- Testes executados:
  Nenhum teste funcional novo era necessário para documentação.
- Riscos ou observações:
  Esses arquivos devem ser mantidos atualizados sempre que houver alteração relevante em fluxo, arquitetura ou testes.

## 2026-06-06 - Convenção de Organização Lógica

- Objetivo:
  Registrar a divisão arquitetural desejada entre `agents`, `services`, `conversation`, `integrations`, `repositories` e `tests`.
- Arquivos alterados:
  `docs/PROJECT_MAP.md`
  `docs/DEVELOPMENT_GUIDE.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  A documentação passou a tratar essa divisão como convenção oficial para orientar novas alterações, sem mover código existente e sem alterar comportamento do sistema.
- Testes executados:
  Nenhum teste funcional era necessário, pois a alteração foi apenas documental.
- Riscos ou observações:
  A convenção está documentada, mas a estrutura física do projeto ainda permanece concentrada em `app/`.

## 2026-06-06 - Base Documental Para State Machine, Contratos e Estratégia de Testes

- Objetivo:
  Registrar os estados atuais, o contrato estrutural futuro dos agentes e a estratégia incremental de testes de conversa sem alterar comportamento de produção.
- Arquivos alterados:
  `docs/STATE_MACHINE.md`
  `docs/CONTRACTS.md`
  `docs/TEST_STRATEGY.md`
  `docs/DEVELOPMENT_GUIDE.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  Documentados os estados atuais em `status_atendimento` e `aguardando_resposta`, os riscos de ambiguidade numérica, o contrato ideal de respostas internas, a estrutura futura proposta para `app/conversation/` e `app/tests/conversation/`, além do plano de implantação em etapas pequenas.
- Testes executados:
  Nenhum teste funcional novo era necessário, pois a alteração foi apenas documental.
- Riscos ou observações:
  O projeto atual ainda depende de decisões distribuídas entre `OrchestratorAgent`, `OrderAgent` e `MessageAgent`; a documentação foi escrita para proteger esse comportamento antes de qualquer migração estrutural.

## 2026-06-06 - Skills Alinhadas com a Arquitetura Lógica Oficial

- Objetivo:
  Atualizar as skills internas para orientar mudanças futuras respeitando a separação lógica entre `agents`, `services`, `conversation`, `integrations`, `repositories` e `tests`.
- Arquivos alterados:
  `docs/skills/01_ajustar_fluxo_conversacional.md`
  `docs/skills/02_ajustar_estados_conversa.md`
  `docs/skills/03_ajustar_pedidos_itens.md`
  `docs/skills/04_ajustar_cardapio_estoque.md`
  `docs/skills/05_ajustar_pagamento_comprovante.md`
  `docs/skills/06_ajustar_horarios.md`
  `docs/skills/07_criar_testes_conversa.md`
  `docs/skills/08_revisar_mensagens_whatsapp.md`
  `docs/DEVELOPMENT_GUIDE.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  Cada skill passou a ter a seção `Arquitetura lógica a respeitar`, orientando onde cada responsabilidade deve nascer conceitualmente, mesmo antes da criação física das pastas futuras.
- Testes executados:
  Nenhum teste funcional novo era necessário, pois a alteração foi apenas documental.
- Riscos ou observações:
  A base ainda continua fisicamente concentrada em `app/`, então as skills agora deixam explícita a diferença entre local físico atual e responsabilidade lógica futura.

## 2026-06-06 - Suíte Inicial de Proteção do Fluxo Conversacional

- Objetivo:
  Criar testes automatizados para proteger o comportamento atual do fluxo conversacional, com foco em ambiguidades numéricas, complementos e fluxos ponta a ponta, sem alterar a lógica de produção.
- Arquivos alterados:
  `app/tests/conversation/__init__.py`
  `app/tests/conversation/base.py`
  `app/tests/conversation/test_numeric_ambiguity.py`
  `app/tests/conversation/test_complements_flow.py`
  `app/tests/conversation/test_order_flow.py`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  Criada uma base compartilhada de runtime fake para testes e uma nova suíte organizada em `app/tests/conversation/`, cobrindo menu principal, entrega, pagamento, complementos, item sem preço e três fluxos ponta a ponta.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  Os testes novos congelam o comportamento atual sem mudar produção. A suíte antiga continua emitindo logs intencionais de fallback/recuperação em alguns cenários de resiliência, mas terminou com status `OK`.

## 2026-06-06 - Expansão de Golden Tests Interrompida por Divergência de Preço

- Objetivo:
  Iniciar a criação de golden tests de conversas completas sem alterar a lógica de produção.
- Arquivos alterados:
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  A expansão foi interrompida antes de criar novos testes porque surgiu divergência entre o golden solicitado e o comportamento atualmente protegido pela suíte.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  O fluxo atual protegido pelos testes usa `marmita para 3 pessoas = R$ 60,00`, o que leva ao total `R$ 72,00` quando somado a `2 refrigerantes`. O golden solicitado pede `R$ 85,00` e total `R$ 97,00`. Como a tarefa proibia corrigir comportamento nesta etapa, nenhum golden test novo foi consolidado para evitar congelar uma expectativa incompatível com o estado atual.

## 2026-06-06 - Base de Testes Alinhada ao Catálogo Oficial

- Objetivo:
  Corrigir apenas a massa de testes e expectativas para refletirem o catálogo oficial, sem alterar a lógica de produção.
- Arquivos alterados:
  `app/tests/conversation/base.py`
  `app/tests/conversation/test_complements_flow.py`
  `app/tests/conversation/test_order_flow.py`
  `app/tests/test_cardapio_day_context.py`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  O catálogo fake dos testes foi alinhado para usar `marmita para 2 pessoas = R$ 65,00`, `marmita para 3 pessoas = R$ 85,00`, `marmita para 4 pessoas = R$ 105,00` e `marmita para 5 pessoas = R$ 125,00`. Também foram atualizados os asserts de totais afetados, como `R$ 90,00` para `marmita para 3 pessoas + 2 ovos adicionais` e `R$ 97,00` para `marmita para 3 pessoas + 2 refrigerantes`.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  Nenhum arquivo de produção foi alterado. Os logs de fallback visíveis na suíte legada continuam sendo parte intencional dos cenários de resiliência e a suíte terminou com status `OK`.

## 2026-06-06 - Golden Tests Interrompidos por Divergência de Sequência Conversacional

- Objetivo:
  Retomar a criação de golden tests de conversas completas esperadas.
- Arquivos alterados:
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  A implementação foi interrompida após simulação das sequências solicitadas, porque duas conversas-base pedidas não correspondem ao comportamento atual do bot.
- Testes executados:
  Simulação manual via `python3 manage.py shell` com o runtime fake de `app/tests/conversation/base.py`
- Riscos ou observações:
  Divergência 1: no fluxo `oi -> 1 -> 2`, o `2` atual não é interpretado como quantidade de marmitex; ele seleciona `Marmita para 2 pessoas`, porque o estado ainda está em `aguardando_produto`.
  Divergência 2: no fluxo de entrega `... -> Rua Bahia 1000 -> 2`, o `2` atual não é interpretado como pagamento; ele é aceito como nome do cliente, porque o estado após endereço é `aguardando_nome_cliente`.
  Como a tarefa proibia corrigir comportamento nesta etapa, nenhum golden test novo foi consolidado para evitar congelar expectativas incompatíveis com o comportamento atual.

## 2026-06-06 - Golden Tests Criados com Base no Fluxo Real Atual

- Objetivo:
  Criar golden tests de conversas completas usando o comportamento real atual do bot, sem alterar produção.
- Arquivos alterados:
  `app/tests/conversation/base.py`
  `app/tests/conversation/test_golden_conversations.py`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  Foi adicionado um helper para executar conversas completas e capturar histórico por passo, além de uma nova suíte de golden tests cobrindo `2 marmitex sem complemento e Pix`, `2 marmitex com água e Pix`, `marmita para 3 pessoas com refrigerantes e dinheiro`, recusa natural de complemento e ambiguidade numérica contextual.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  Os golden tests validam trechos importantes das mensagens para reduzir fragilidade. A suíte legada continua emitindo logs intencionais de fallback em cenários de resiliência e terminou com status `OK`.

## 2026-06-06 - Contrato Estruturado Auxiliar em Paralelo aos Retornos Atuais

- Objetivo:
  Criar um contrato estruturado leve para padronizar retornos dos agentes em testes e futura instrumentação, sem alterar o comportamento atual do bot.
- Arquivos alterados:
  `app/conversation/__init__.py`
  `app/conversation/contracts.py`
  `app/tests/conversation/test_agent_contracts.py`
  `docs/CONTRACTS.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  Foi criado `AgentResponseContract` com adaptadores para respostas atuais de `OrderAgent`, `OrchestratorAgent` e `MessageAgent`. O contrato preserva a mensagem original, mantém o payload bruto em `raw_response` e não substitui `response`, `final_response` ou `next_question` nesta etapa.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  O contrato ainda é apenas camada auxiliar para testes, logs e migração gradual. O fluxo real do bot e os retornos atuais dos agentes continuam inalterados.

## 2026-06-06 - Golden Tests Validados com AgentResponseContract

- Objetivo:
  Usar `AgentResponseContract` como validação auxiliar nos golden tests, sem integrar o contrato ao fluxo real.
- Arquivos alterados:
  `app/tests/conversation/base.py`
  `app/tests/conversation/test_golden_conversations.py`
  `docs/CONTRACTS.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  O helper de conversa passou a guardar o payload bruto do orquestrador e os golden tests agora verificam `success`, preservação de `message`, preservação de `raw_response`, ausência de `errors` e `requires_human=False` nos fluxos normais. Também foram adicionadas validações auxiliares de `next_state` e `awaiting_response` quando esses campos estão disponíveis no payload atual.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  Limitação atual documentada: respostas informativas do `OrchestratorAgent` que não carregam `state` ou `order_state` ainda não permitem ao contrato projetar `next_state` e `awaiting_response`. Nessas etapas, os testes validam apenas os campos disponíveis sem forçar mudança em produção.

## 2026-06-06 - StateMachine Auxiliar Criada para Testes e Documentação

- Objetivo:
  Criar uma state machine auxiliar para documentar e validar transições esperadas do fluxo conversacional, sem controlar o fluxo real do bot.
- Arquivos alterados:
  `app/conversation/__init__.py`
  `app/conversation/states.py`
  `app/conversation/transitions.py`
  `app/conversation/state_machine.py`
  `app/tests/conversation/test_state_machine.py`
  `docs/STATE_MACHINE.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  Foram declarados enums/constantes de estados e esperas, uma tabela declarativa de transições conhecidas e uma `ConversationStateMachine` auxiliar com métodos para obter próximo estado esperado, validar transição e explicar transições mapeadas ou não mapeadas.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  A state machine continua totalmente auxiliar e desacoplada da produção. Transições ainda não declaradas retornam `not_mapped` e isso não é tratado como erro de produção nesta fase.

## 2026-06-06 - StateMachine Integrada aos Golden Tests como Validadora Auxiliar

- Objetivo:
  Comparar transições reais capturadas nos golden tests com as transições esperadas da `ConversationStateMachine`, sem alterar o fluxo de produção.
- Arquivos alterados:
  `app/tests/conversation/base.py`
  `app/tests/conversation/test_golden_conversations.py`
  `docs/STATE_MACHINE.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  O helper de conversa passou a capturar `before_awaiting_response` e foi criado um assert dedicado para validar transições estáveis com a tabela declarativa da state machine. Os golden tests agora verificam transições reais como `menu_principal -> produto`, `produto -> quantidade`, `quantidade -> complemento`, `complemento -> tipo_entrega`, `tipo_entrega -> nome_cliente/endereco`, `nome_cliente -> forma_pagamento` e `forma_pagamento -> comprovante/confirmacao`.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  A validação continua restrita a pontos estáveis do fluxo. Transições não mapeadas seguem aceitáveis apenas quando explicitamente ignoradas e não geram mudança em produção.

## 2026-06-06 - Camada de Observabilidade Criada para Testes de Conversa

- Objetivo:
  Criar snapshots estruturados das conversas nos testes para facilitar depuração, comparação e futuras regressões, sem alterar comportamento de produção.
- Arquivos alterados:
  `app/tests/conversation/snapshots.py`
  `app/tests/conversation/test_conversation_snapshots.py`
  `app/tests/conversation/test_golden_conversations.py`
  `docs/TEST_STRATEGY.md`
  `docs/CHANGELOG_IA.md`
- Resumo da mudança:
  Foi criado um utilitário de snapshot em memória que resume cada passo da conversa com mensagem do cliente, resposta do bot, estado antes e depois, dados do contrato auxiliar, validação da state machine, itens do pedido, total, forma de recebimento e forma de pagamento. Os golden tests agora geram snapshots para melhorar mensagens de falha e há uma suíte específica validando a estrutura e o formatador legível.
- Testes executados:
  `python3 manage.py test app.tests.conversation`
  `python3 manage.py test app.tests.test_cardapio_day_context`
- Riscos ou observações:
  Os snapshots são apenas auxiliares de teste, não são logs de produção e não alteram o comportamento real do bot.

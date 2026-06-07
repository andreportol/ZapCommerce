# State Machine

## Objetivo

Este documento mapeia a máquina de estados atual da Marmitaria IA como ela existe hoje no código. Ele não descreve uma implementação nova. Ele registra o comportamento atual para reduzir regressões quando o fluxo conversacional for alterado.

## Fonte Atual Do Estado

Hoje o estado da conversa está distribuído em dois eixos principais:

- `status_atendimento` em `app/agents/conversation_state.py`
- `aguardando_resposta` em `app/agents/conversation_state.py`

Na prática, o fluxo depende dos dois campos ao mesmo tempo. Em vários pontos, `status_atendimento` representa a macroetapa e `aguardando_resposta` resolve a pergunta exata pendente.

## Estados Atuais Em `status_atendimento`

### `inicio`

- Significado:
  Conversa sem pedido ativo ou recém-recuperada.
- Mensagens esperadas:
  saudação, menu principal `1/2/3/4`, pedido direto, consulta de cardápio, consulta de horário, localização.
- Próximos estados possíveis:
  `consultando_cardapio`, `fazendo_pedido`, `aguardando_confirmacao_fazer_pedido`, `fora_horario`, `encaminhar_atendente`.
- Ações executadas:
  exibição do menu principal, início do fluxo de pedido, respostas informativas, reset seguro após fallback.

### `fora_horario`

- Significado:
  atendimento fora da janela de pedidos/encomendas.
- Mensagens esperadas:
  consultas informativas, retomada posterior, novo pedido em horário válido.
- Próximos estados possíveis:
  `inicio`, `consultando_cardapio`, `aguardando_confirmacao_fazer_pedido`.
- Ações executadas:
  bloqueio de novos pedidos, resposta com horários válidos, possível reset de contexto anterior.

### `consultando_cardapio`

- Significado:
  cliente está consultando cardápio do dia ou semana.
- Mensagens esperadas:
  `hoje`, dia da semana, `1/2/3/4/5/6` para dias, continuidade de consulta.
- Próximos estados possíveis:
  `consultando_cardapio`, `aguardando_confirmacao_fazer_pedido`, `fazendo_pedido`, `inicio`.
- Ações executadas:
  resposta do cardápio, marcação de espera para `dia_cardapio`, oferta indireta para fazer pedido.

### `aguardando_confirmacao_fazer_pedido`

- Significado:
  o bot ofereceu iniciar pedido e aguarda um aceite simples.
- Mensagens esperadas:
  `sim`, `quero`, `ok`, `pode ser`, `quero fazer pedido`.
- Próximos estados possíveis:
  `fazendo_pedido`, `aguardando_produto`, `inicio`.
- Ações executadas:
  inicia o prompt oficial do pedido ou volta ao menu por recuperação.

### `fazendo_pedido`

- Significado:
  o cliente entrou no fluxo de pedido, mas ainda pode faltar produto definido.
- Mensagens esperadas:
  pedido natural, escolha de produto, quantidade, dúvidas paralelas compatíveis com pedido.
- Próximos estados possíveis:
  `aguardando_produto`, `aguardando_quantidade`, `aguardando_pessoas_marmita`, `aguardando_tipo_entrega`, `encaminhar_atendente`.
- Ações executadas:
  parsing do pedido, definição de item principal, continuação do fluxo.

### `aguardando_produto`

- Significado:
  o sistema precisa que o cliente escolha o produto principal ou o tipo de marmita.
- Mensagens esperadas:
  número do menu de produtos, `marmitex`, `marmita para 3 pessoas`, `2`, `3`, `4`, `5`.
- Próximos estados possíveis:
  `aguardando_quantidade`, `aguardando_pessoas_marmita`, `aguardando_tipo_entrega`, `encaminhar_atendente`.
- Ações executadas:
  resolve item do catálogo principal ou pede esclarecimento do tipo da marmita.

### `aguardando_pessoas_marmita`

- Significado:
  pedido de `marmita` sem tamanho explícito ou com necessidade de informar quantas pessoas.
- Mensagens esperadas:
  `2`, `3`, `4`, `5`, `para 3 pessoas`.
- Próximos estados possíveis:
  `aguardando_tipo_entrega`, `encaminhar_atendente`, permanência no mesmo estado.
- Ações executadas:
  monta o item familiar, calcula subtotal ou encaminha para consulta da proprietária acima do limite configurado.

### `aguardando_quantidade`

- Significado:
  produto principal já foi resolvido, mas ainda falta quantidade.
- Mensagens esperadas:
  `1`, `2`, `3`, `quero 2`.
- Próximos estados possíveis:
  `aguardando_tipo_entrega`, permanência no mesmo estado.
- Ações executadas:
  monta item principal, calcula subtotal e pode abrir etapa de complementos.

### `aguardando_tipo_entrega`

- Significado:
  pedido principal já existe e o próximo macrobloco é escolher complementos ou entrega/retirada.
- Mensagens esperadas:
  `1`, `2`, `entrega`, `retirada`, endereço direto, respostas da etapa de complementos.
- Próximos estados possíveis:
  `aguardando_endereco`, `aguardando_nome_cliente`, permanência no mesmo estado.
- Ações executadas:
  oferta de complementos quando `aguardando_resposta` ainda está em complemento, ou captura do modo de recebimento quando essa etapa termina.

### `aguardando_confirmacao_item`

- Significado:
  existe item principal com observação pendente de confirmação.
- Mensagens esperadas:
  confirmação positiva, correção da observação, continuidade do pedido.
- Próximos estados possíveis:
  `aguardando_tipo_entrega`, permanência no mesmo estado.
- Ações executadas:
  confirma item ajustado e segue para complemento ou entrega.

### `aguardando_endereco`

- Significado:
  cliente escolheu entrega e o sistema precisa do endereço.
- Mensagens esperadas:
  endereço livre, bairro, rua, número, complemento.
- Próximos estados possíveis:
  `aguardando_nome_cliente`, permanência no mesmo estado.
- Ações executadas:
  salva endereço e avança para coleta do nome.

### `aguardando_nome_cliente`

- Significado:
  pedido precisa de identificação do cliente.
- Mensagens esperadas:
  nome em texto natural.
- Próximos estados possíveis:
  `aguardando_pagamento`, permanência no mesmo estado.
- Ações executadas:
  persiste nome do cliente e abre escolha de pagamento.

### `aguardando_pagamento`

- Significado:
  pedido montado, aguardando forma de pagamento.
- Mensagens esperadas:
  `1`, `2`, `3`, `pix`, `dinheiro`, `cartão`.
- Próximos estados possíveis:
  `aguardando_comprovante`, `aguardando_confirmacao`.
- Ações executadas:
  define forma de pagamento, monta instruções Pix ou resumo final.

### `aguardando_comprovante`

- Significado:
  cliente escolheu Pix e precisa enviar comprovante.
- Mensagens esperadas:
  texto dizendo que vai enviar, imagem, PDF, texto de comprovante.
- Próximos estados possíveis:
  `aguardando_conferencia_pagamento`, permanência no mesmo estado, `inicio` em cancelamento.
- Ações executadas:
  `PaymentProofAgent` detecta recebimento e move para conferência manual.

### `aguardando_conferencia_pagamento`

- Significado:
  comprovante já foi recebido e aguarda validação da equipe.
- Mensagens esperadas:
  perguntas de status, novo pedido.
- Próximos estados possíveis:
  permanência no mesmo estado, `fazendo_pedido` em novo pedido.
- Ações executadas:
  responde que o comprovante está em conferência, sem confirmar pagamento automaticamente.

### `aguardando_confirmacao`

- Significado:
  pedido está montado e falta a confirmação final do cliente.
- Mensagens esperadas:
  confirmação, alteração, cancelamento.
- Próximos estados possíveis:
  `inicio` por cancelamento, permanência no mesmo estado, finalização externa do pedido.
- Ações executadas:
  entrega resumo final, aceita mudança final ou confirmação do pedido.

### `encaminhar_atendente`

- Significado:
  fluxo precisa de atendimento humano ou consulta da proprietária.
- Mensagens esperadas:
  retomada manual, novo pedido, continuidade fora do fluxo local.
- Próximos estados possíveis:
  `inicio`, `fazendo_pedido`, permanência até ação humana.
- Ações executadas:
  responde com encaminhamento humano ou consulta da proprietária.

## Esperas Atuais Em `aguardando_resposta`

### `menu_principal`

- Uso atual:
  marca retorno ao menu principal.
- Onde aparece:
  recuperação e mais informações.
- Risco:
  números `1/2/3/4` podem cair no menu principal se não houver contexto de pedido ativo.

### `dia_cardapio`

- Uso atual:
  cliente precisa escolher dia do cardápio.
- Entradas esperadas:
  nomes dos dias e números do menu semanal.
- Próximo caminho:
  permanece em cardápio ou volta para `inicio`.

### `entrega_bairro_ou_endereco`

- Uso atual:
  follow-up informativo sobre taxa/área de entrega.
- Entradas esperadas:
  bairro, endereço, pergunta sobre entrega.
- Próximo caminho:
  limpa a espera depois da resposta informativa.

### `fora_horario`

- Uso atual:
  marca que a última resposta foi bloqueio por horário.
- Entradas esperadas:
  consultas gerais, novo contato posterior.
- Próximo caminho:
  volta para `inicio` ou `consultando_cardapio`.

### `produto`

- Uso atual:
  retorno de `_awaiting_field`; hoje representa que ainda falta item principal.
- Observação:
  o prompt real costuma aparecer como seleção de produto, enquanto a resolução prática usa muito `tipo_marmita` e `aguardando_produto`.

### `tipo_marmita`

- Uso atual:
  pedido de esclarecimento entre `marmitex individual` e `marmita para N pessoas`.
- Entradas esperadas:
  `1`, `2`, `3`, `4`, `5`, `marmitex`, `3 pessoas`.
- Próximo caminho:
  `quantidade` ou aplicação direta do item.

### `quantidade`

- Uso atual:
  aguarda quantidade do item principal.
- Entradas esperadas:
  número inteiro válido.
- Próximo caminho:
  `complemento` ou `tipo_entrega`.

### `complemento`

- Uso atual:
  lista automática de bebidas, adicionais e sobremesas com preço válido.
- Entradas esperadas:
  número da lista, nome do complemento, frases como `não quero`, `sem bebida`, `pode seguir`.
- Próximo caminho:
  `quantidade_complemento`, `mais_complementos` ou `tipo_entrega`.

### `quantidade_complemento`

- Uso atual:
  complemento já foi identificado, mas falta a quantidade.
- Entradas esperadas:
  número inteiro válido.
- Próximo caminho:
  `mais_complementos` ou retorno para `complemento` se o item pendente se perder.

### `mais_complementos`

- Uso atual:
  pergunta se o cliente deseja adicionar outro complemento.
- Entradas esperadas:
  `1`, `2`, `sim`, `não`, nome direto de um novo complemento.
- Próximo caminho:
  `complemento`, `quantidade_complemento` ou `tipo_entrega`.

### `tipo_entrega`

- Uso atual:
  escolha entre entrega e retirada.
- Entradas esperadas:
  `1`, `2`, `entrega`, `retirada`, endereço direto.
- Próximo caminho:
  `endereco` ou `nome_cliente`.

### `endereco`

- Uso atual:
  espera endereço de entrega.
- Entradas esperadas:
  endereço livre.
- Próximo caminho:
  `nome_cliente`.

### `nome_cliente`

- Uso atual:
  espera nome do cliente.
- Entradas esperadas:
  texto com nome válido.
- Próximo caminho:
  `forma_pagamento`.

### `forma_pagamento`

- Uso atual:
  espera Pix, dinheiro ou cartão.
- Entradas esperadas:
  `1`, `2`, `3`, `pix`, `dinheiro`, `cartão`.
- Próximo caminho:
  `comprovante` ou `confirmacao`.

### `confirmacao`

- Uso atual:
  espera confirmação final do pedido.
- Entradas esperadas:
  `sim`, confirmação livre, pedido de alteração, cancelamento.
- Próximo caminho:
  confirmação externa do pedido, novo pedido ou cancelamento.

### `confirmacao_item`

- Uso atual:
  confirma item com observação pendente.
- Entradas esperadas:
  confirmação positiva ou correção.
- Próximo caminho:
  `complemento` ou `tipo_entrega`.

### `comprovante`

- Uso atual:
  espera comprovante do Pix.
- Entradas esperadas:
  anexo, imagem, PDF, texto de comprovante.
- Próximo caminho:
  `conferencia_pagamento`.

### `conferencia_pagamento`

- Uso atual:
  marca conferência manual pendente.
- Entradas esperadas:
  consultas ou novo pedido.
- Próximo caminho:
  novo fluxo ou permanência em conferência.

### `pessoas_marmita`

- Uso atual:
  espera quantidade de pessoas da marmita familiar.
- Entradas esperadas:
  `2`, `3`, `4`, `5`.
- Próximo caminho:
  `complemento` ou `tipo_entrega`.

### `confirmacao_fazer_pedido`

- Uso atual:
  espera aceite para começar um pedido depois de resposta informativa.
- Entradas esperadas:
  `sim`, `quero`, `ok`.
- Próximo caminho:
  início do fluxo de pedido.

### `consulta_proprietaria`

- Uso atual:
  encaminhamento por limite operacional ou necessidade humana.
- Entradas esperadas:
  sem continuidade automática garantida.
- Próximo caminho:
  atendimento humano ou reinício posterior.

## Transições Mais Importantes Do Fluxo Atual

Fluxo principal típico:

1. `inicio`
2. `fazendo_pedido` ou `aguardando_produto`
3. `aguardando_quantidade` ou `aguardando_pessoas_marmita`
4. `aguardando_tipo_entrega` com `aguardando_resposta="complemento"`
5. `aguardando_tipo_entrega` com `aguardando_resposta="quantidade_complemento"` quando necessário
6. `aguardando_tipo_entrega` com `aguardando_resposta="mais_complementos"`
7. `aguardando_tipo_entrega` com `aguardando_resposta="tipo_entrega"`
8. `aguardando_endereco` ou `aguardando_nome_cliente`
9. `aguardando_pagamento`
10. `aguardando_comprovante` ou `aguardando_confirmacao`
11. `aguardando_conferencia_pagamento` quando Pix exige comprovante

## Riscos De Ambiguidade Encontrados

### Números `1`, `2`, `3` e `4`

- `1` no menu principal significa `Fazer pedido`.
- `1` no cardápio semanal pode significar um dia específico.
- `1` na seleção de produtos significa `Marmitex individual`.
- `1` em `mais_complementos` significa `Sim`.
- `1` em `tipo_entrega` significa `Entrega`.
- `1` em `forma_pagamento` significa `Pix`.
- `1` em `quantidade` significa apenas quantidade.

- `2` no menu principal significa `Saber o cardápio`.
- `2` em complementos pode significar o segundo item da lista.
- `2` em `mais_complementos` significa `Não, seguir pedido`.
- `2` em `tipo_entrega` significa `Retirada`.
- `2` em `forma_pagamento` significa `Dinheiro`.
- `2` em `pessoas_marmita` significa `marmita para 2 pessoas`.

- `3` no menu principal significa `Mais informações`.
- `3` em `forma_pagamento` significa `Cartão`.
- `3` em seleção de produto pode significar `marmita para 3 pessoas`.

- `4` no menu principal significa `Falar com a atendente`.
- `4` em seleção de produto pode significar `marmita para 4 pessoas`.
- `4` em complementos pode ser um item real ou a opção `Não, obrigado`, dependendo do tamanho da lista.

### Pontos Mais Sensíveis

- O projeto hoje não depende apenas de `status_atendimento`; ele depende fortemente de `aguardando_resposta`.
- A etapa de complementos reutiliza `status_atendimento=aguardando_tipo_entrega`, o que funciona, mas mistura duas macroetapas no mesmo status.
- O `MessageAgent` bloqueia leitura do menu principal se detectar etapa pendente de pedido, o que evita várias colisões numéricas.
- Mesmo assim, qualquer ajuste em parsing numérico deve validar pelo menos:
  `menu principal`, `dia_cardapio`, `produto`, `quantidade`, `complemento`, `mais_complementos`, `tipo_entrega` e `forma_pagamento`.

## Estrutura Futura Proposta

Sem implementar agora, a estrutura futura recomendada é:

```text
app/conversation/
    states.py
    transitions.py
    state_machine.py
    contracts.py

app/tests/conversation/
    test_order_flow.py
    test_complements_flow.py
    test_payment_flow.py
    test_numeric_ambiguity.py
```

Objetivo dessa evolução:

- separar estado declarado de transições
- tornar o próximo passo determinístico por estado
- reduzir parsing implícito espalhado em `OrderAgent` e `OrchestratorAgent`
- isolar testes de ambiguidade numérica por etapa

## Status Atual Da Implementação Auxiliar

Nesta etapa, foi criada uma state machine auxiliar em:

```text
app/conversation/states.py
app/conversation/transitions.py
app/conversation/state_machine.py
```

Uso atual:

- apenas em testes e documentação
- não controla o fluxo real do bot
- não substitui `status_atendimento`
- não substitui `aguardando_resposta`
- agora também é usada nos golden tests como validadora auxiliar de transições estáveis

Comportamento desta camada auxiliar:

- cobre apenas transições já conhecidas e estabilizadas pelos testes atuais
- responde `not_mapped` para transições ainda não declaradas
- não trata transição não mapeada como erro de produção nesta fase
- nos golden tests, transições não mapeadas continuam aceitáveis quando explicitamente ignoradas

Objetivo imediato:

- documentar transições esperadas
- validar coerência dos fluxos já protegidos pelos golden tests
- preparar migração gradual futura sem acoplar a produção agora

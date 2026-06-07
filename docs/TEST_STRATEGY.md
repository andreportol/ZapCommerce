# Test Strategy

## Objetivo

Este documento define a estratégia recomendada para testes de conversa da Marmitaria IA, com foco em regressões de fluxo, ambiguidade numérica e segurança de mudanças incrementais.

## Princípio Central

Antes de evoluir a máquina de estados, o comportamento atual precisa estar protegido por testes de regressão. A prioridade não é “testar implementação”. A prioridade é congelar o comportamento esperado do atendimento.

## Camadas De Teste Recomendadas

### 1. Testes De Fluxo Completo

Cobrem conversas ponta a ponta, do início até a etapa final do fluxo.

Exemplos:

- pedido simples com retirada
- pedido com entrega
- pedido com complementos
- pedido com Pix e comprovante
- pedido com dinheiro
- pedido com cartão

Objetivo:

- validar transições reais entre etapas
- validar texto final mais importante
- validar persistência do estado entre mensagens

### 2. Testes Por Estado

Cobrem cada etapa isoladamente, forçando um `ConversationState` específico e enviando uma mensagem compatível.

Estados prioritários:

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

Objetivo:

- validar qual entrada é aceita em cada etapa
- validar `status_atendimento` e `aguardando_resposta` após a mensagem
- reduzir regressões causadas por alterações locais

### 3. Testes De Ambiguidade Numérica

Devem proteger os casos em que `1`, `2`, `3` e `4` podem significar coisas diferentes conforme o contexto.

Coberturas mínimas:

- `1` no menu principal
- `1` em seleção de produto
- `1` em quantidade
- `1` em complementos
- `1` em `mais_complementos`
- `1` em `tipo_entrega`
- `1` em `forma_pagamento`
- `2` em complementos não pode virar retirada por engano
- `2` em pagamento não pode virar menu/cardápio

Objetivo:

- garantir que o contexto mande mais que o número isolado
- impedir colisões entre menu global e subfluxos

### 4. Testes De Complementos

Cobrem:

- cliente recusa complementos
- cliente escolhe complemento por número
- cliente escolhe complemento por texto natural
- cliente informa quantidade junto do complemento
- cliente informa quantidade em segunda etapa
- cliente adiciona mais de um complemento
- complemento ativo sem preço não entra no cálculo

Objetivo:

- proteger a etapa mais suscetível a colisões com `1` e `2`
- validar recalculo de total sem mexer em pagamento

### 5. Testes De Pagamento

Cobrem:

- Pix abre instruções corretas
- dinheiro segue para confirmação final
- cartão segue para confirmação final
- comprovante só muda para conferência quando realmente identificado

Objetivo:

- impedir regressão em uma etapa crítica do negócio
- garantir que o bot não confirme pagamento automaticamente

### 6. Testes De Horário

Cobrem:

- bloqueio fora do horário de pedidos
- respostas informativas ainda disponíveis fora do horário
- texto de horários permanece coerente

Objetivo:

- separar regras de disponibilidade de regras de pedido

### 7. Testes De Comprovante

Cobrem:

- recebimento por texto
- recebimento por imagem
- recebimento por PDF
- ack sem comprovante mantém estado pendente
- conferência manual não confirma pedido automaticamente

### 8. Golden Tests De Conversa

Golden tests devem armazenar conversas esperadas como sequência de entradas e saídas relevantes.

Exemplo conceitual:

```text
usuario: quero 2 marmitex
bot: resumo parcial + complementos
usuario: nao quero
bot: entrega ou retirada
usuario: 2
bot: pedir nome
usuario: Andre
bot: pedir pagamento
```

Objetivo:

- detectar mudanças acidentais de mensagem e transição
- facilitar revisão de fluxo por leitura humana

Snapshots estruturados em testes:

- podem ser gerados em memória para cada conversa
- ajudam a depurar em qual passo a regressão aconteceu
- podem registrar mensagem do cliente, resposta do bot, estados antes e depois, total, itens e validação auxiliar de contrato/state machine
- não são logs de produção
- não alteram o comportamento real do sistema

## Cobertura Mínima Recomendada

Toda alteração em fluxo conversacional deve validar pelo menos:

1. um teste ponta a ponta do fluxo afetado
2. um teste por estado da etapa modificada
3. um teste de ambiguidade numérica se houver opções numeradas
4. um teste de não regressão em pagamento quando o fluxo encostar em pedido

## Estrutura Futura Proposta

Sem implementar agora, a estrutura recomendada é:

```text
app/tests/conversation/
    test_order_flow.py
    test_complements_flow.py
    test_payment_flow.py
    test_numeric_ambiguity.py
```

Sugestão de responsabilidade:

- `test_order_flow.py`
  fluxos base de pedido e entrega/retirada
- `test_complements_flow.py`
  bebidas, adicionais, sobremesas e totais
- `test_payment_flow.py`
  Pix, dinheiro, cartão, comprovante e conferência
- `test_numeric_ambiguity.py`
  colisões entre menu global e subestados

## O Que Já Existe Hoje

Hoje a suíte principal está concentrada em:

- `app/tests/test_cardapio_day_context.py`

Ela já cobre partes importantes de:

- cardápio por dia
- pedido principal
- complementos
- entrega/retirada
- pagamento
- comprovante
- recuperação de estado

## Como Evoluir Sem Refatorar Tudo

### Etapa 1

Documentar estados e contratos atuais.

### Etapa 2

Criar mais testes de conversa para o comportamento atual, antes de mexer em estrutura.

### Etapa 3

Introduzir helpers de asserção para:

- `status_atendimento`
- `aguardando_resposta`
- `valor_total`
- texto-chave da resposta

### Etapa 4

Separar a suíte em `app/tests/conversation/` mantendo os testes antigos coexistindo por um tempo.

### Etapa 5

Criar golden tests com casos reais do negócio.

## Checklist Mínimo Antes De Mudar Fluxo

1. localizar testes existentes da etapa afetada
2. adicionar um teste cobrindo o novo cenário
3. adicionar um teste cobrindo o cenário antigo mais próximo
4. verificar colisões de `1`, `2`, `3` e `4`
5. rodar a suíte específica da conversa

## Checklist Mínimo Depois Da Mudança

1. confirmar estado final esperado
2. confirmar `aguardando_resposta` esperado
3. confirmar total do pedido quando aplicável
4. confirmar que Pix, comprovante e conferência não regrediram
5. registrar o que foi validado no `CHANGELOG_IA.md`

## Plano De Implantação Recomendado

### Etapa 1

Documentar estados atuais.

### Etapa 2

Criar testes de conversa para o comportamento atual.

### Etapa 3

Criar contratos estruturados sem mudar o texto das respostas.

### Etapa 4

Criar `StateMachine` apenas como camada auxiliar.

### Etapa 5

Migrar decisões de próximo estado aos poucos para a `StateMachine`.

### Etapa 6

Criar catálogo configurável por categoria de produto.

### Etapa 7

Criar feature flags para ativar ou desativar etapas como complementos e sobremesas.

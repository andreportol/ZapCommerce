# Contracts

## Objetivo

Este documento define o contrato estrutural recomendado para respostas internas dos agentes. A meta é padronizar saídas sem mudar agora o texto que o cliente recebe nem refatorar o projeto inteiro.

## Problema Atual

Hoje os agentes retornam dicionários parecidos, mas não totalmente padronizados. Campos como `response`, `next_question`, `state`, `pricing`, `final_response`, `database`, `intent` e `order_state` aparecem com formatos diferentes dependendo do ponto do fluxo.

Isso dificulta:

- validar transições de estado de forma uniforme
- criar testes mais previsíveis
- detectar regressões entre agentes
- introduzir uma `StateMachine` auxiliar sem acoplamento excessivo

## Contrato Ideal Recomendado

Contrato lógico sugerido para respostas de agentes de conversa:

```json
{
  "success": true,
  "message": "Perfeito 😊 Atualizei seu pedido...",
  "next_state": "aguardando_tipo_entrega",
  "next_waiting": "mais_complementos",
  "intent": "fazer_pedido",
  "order_updated": true,
  "payment_updated": false,
  "requires_human": false,
  "errors": [],
  "meta": {
    "current_state": "aguardando_tipo_entrega",
    "current_waiting": "quantidade_complemento",
    "pricing": {
      "can_calculate": true,
      "needs_owner": false,
      "unit_price": 4.0,
      "total_price": 46.0
    }
  }
}
```

## Campos Recomendados

### `success`

- Tipo:
  `bool`
- Significado:
  indica se o agente conseguiu processar a etapa atual sem fallback excepcional.

### `message`

- Tipo:
  `str`
- Significado:
  texto final que deverá ser entregue ao usuário naquela etapa.
- Regra:
  este campo deve preservar exatamente a mensagem atual do sistema quando a padronização começar.

### `next_state`

- Tipo:
  `str`
- Significado:
  valor de `status_atendimento` esperado após a execução.

### `next_waiting`

- Tipo:
  `str`
- Significado:
  valor de `aguardando_resposta` esperado após a execução.

### `intent`

- Tipo:
  `str`
- Significado:
  intenção de alto nível associada ao processamento atual, por exemplo `fazer_pedido`, `consultar_cardapio`, `cancelar`, `fora_horario`.

### `order_updated`

- Tipo:
  `bool`
- Significado:
  indica se houve alteração em itens, quantidade, total, entrega ou dados do pedido.

### `payment_updated`

- Tipo:
  `bool`
- Significado:
  indica se forma de pagamento, comprovante ou etapa de conferência mudou.

### `requires_human`

- Tipo:
  `bool`
- Significado:
  marca quando o fluxo precisa de proprietária, atendente ou conferência externa.

### `errors`

- Tipo:
  `list[str]`
- Significado:
  coleção de erros estruturados para log, teste e fallback.

### `meta`

- Tipo:
  `dict`
- Significado:
  espaço para contexto auxiliar sem contaminar o contrato principal.
- Exemplos:
  `pricing`, `recognized_product`, `selected_option`, `proof_detected`, `fallback_reason`.

## Mapeamento Do Formato Atual Para O Futuro Contrato

Hoje, sem alterar comportamento, o mapeamento conceitual mais próximo é:

- `response` ou `final_response` -> `message`
- `state.status_atendimento` -> `next_state`
- `state.aguardando_resposta` -> `next_waiting`
- mudanças em `itens_pedido`, `valor_total`, `tipo_entrega`, `endereco`, `forma_pagamento` -> `order_updated` e `payment_updated`
- `pricing.needs_owner` ou `status_atendimento=encaminhar_atendente` -> `requires_human`

## Como Usar Esse Contrato Sem Quebrar O Comportamento Atual

Implementação futura recomendada, em etapas pequenas:

1. criar helpers que recebam a resposta atual do agente e gerem uma versão estruturada em paralelo
2. manter `response` e `final_response` exatamente como estão
3. usar o contrato apenas em testes e logs no início
4. depois fazer o `OrchestratorAgent` consumir o contrato internamente, sem mudar texto final
5. só por último remover retornos antigos, se a suíte de regressão estiver completa

## Regra De Compatibilidade

Enquanto o contrato novo não virar padrão de produção:

- não remover `response`
- não remover `next_question`
- não remover `final_response`
- não alterar textos atuais para “caber” no contrato
- não exigir mudança imediata em todos os agentes

O contrato deve nascer como camada auxiliar, não como quebra de interface.

## Contratos Recomendados Por Tipo De Agente

### Agentes de conversa

Devem preencher:

- `success`
- `message`
- `next_state`
- `next_waiting`
- `intent`
- `order_updated`
- `payment_updated`
- `requires_human`
- `errors`

### Agentes informativos

Podem preencher de forma mínima:

```json
{
  "success": true,
  "message": "Funcionamos nos seguintes horários...",
  "next_state": "inicio",
  "next_waiting": "",
  "intent": "horario_funcionamento",
  "order_updated": false,
  "payment_updated": false,
  "requires_human": false,
  "errors": []
}
```

### Agentes com encaminhamento humano

Devem marcar explicitamente:

```json
{
  "success": true,
  "message": "Vou encaminhar seu atendimento para a atendente.",
  "next_state": "encaminhar_atendente",
  "next_waiting": "consulta_proprietaria",
  "intent": "falar_atendente",
  "order_updated": false,
  "payment_updated": false,
  "requires_human": true,
  "errors": []
}
```

## Estrutura Futura Proposta

O contrato deve morar futuramente em:

```text
app/conversation/contracts.py
```

Estruturas recomendadas:

- `ConversationResult`
- `TransitionDecision`
- `ValidationError`

Isso permite validar, em teste, que:

- toda transição declara estado de saída
- toda resposta informa se houve alteração de pedido
- toda etapa humana é explicitamente marcada

## Regras De Segurança

- não mudar o texto do cliente ao introduzir o contrato
- não misturar persistência de banco com serialização do contrato
- não usar o contrato para esconder exceções; registrar erros reais em `errors`
- não acoplar o contrato a um agente específico

## Primeira Aplicação Segura Recomendada

A primeira aplicação segura é criar um adaptador leve para `OrderAgent` e `OrchestratorAgent` que:

- recebe o dict atual
- deriva `success`, `message`, `next_state`, `next_waiting`
- não altera nenhuma decisão do fluxo
- serve apenas para testes, logs e futura migração incremental

## Status Atual Da Implementação

Nesta etapa, o contrato auxiliar foi criado em:

```text
app/conversation/contracts.py
```

Estrutura inicial implementada:

- `AgentResponseContract`
- `from_order_agent_response(...)`
- `from_orchestrator_response(...)`
- `from_message_agent_response(...)`

Importante:

- o contrato existe apenas como camada auxiliar/adaptadora
- ele ainda não substitui `response`, `final_response`, `next_question` ou os retornos reais dos agentes
- os agentes continuam respondendo exatamente como antes
- o contrato está sendo usado primeiro em testes, incluindo os golden tests de conversa, e poderá ser usado futuramente em logs, testes mais estruturados e migração gradual para `StateMachine`
- limitação atual: respostas informativas do `OrchestratorAgent` que não carregam `order_state` ou `state` no payload ainda não projetam `next_state` e `awaiting_response` pelo contrato; nesses casos, os testes validam apenas os campos disponíveis, como `message`, `success`, `errors`, `requires_human` e `raw_response`

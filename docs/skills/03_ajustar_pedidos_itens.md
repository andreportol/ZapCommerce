# Skill 03 - Ajustar Pedidos, Itens e Totais

## Objetivo

Orientar mudanças em itens do pedido, quantidade, totalização, complementos e persistência do pedido.

## Quando Usar

- inclusão de item no pedido
- alteração de cálculo de subtotal ou total
- revisão de quantidade
- ajuste de itens pendentes
- revisão da persistência de `Pedido` e `ItemPedido`

## Arquitetura Lógica a Respeitar

- `services/`
  é o lugar lógico principal para cálculo de total, itens, quantidades, complementos e validações de produto. Esta skill deve orientar futuras extrações para algo como `OrderService` e `ProductService`.
- `agents/`
  devem apenas interpretar a mensagem do cliente e acionar a regra de pedido necessária.
- `conversation/`
  deve controlar em que etapa do fluxo o pedido está, mas não concentrar cálculo de subtotal, total ou fusão de itens.
- `integrations/`
  não devem carregar regra de pedido.
- `repositories/`
  entram quando o acesso a catálogo, itens e snapshots de pedido exigir uma camada própria.
- `tests/`
  validam totalização, persistência e regressão de fluxo.

Regra prática:

- se a mudança for “quanto custa”, “como soma”, “como junta item”, “como valida item”, ela pertence logicamente a `services/`
- se a mudança for “quando perguntar” ou “qual próximo passo”, ela pertence logicamente a `conversation/`

## Arquivos Prováveis Envolvidos

- `app/agents/order_agent.py`
- `app/order_catalog.py`
- `app/models.py`
- `app/agents/conversation_state.py`
- `app/tests/test_cardapio_day_context.py`
- `docs/CONTRACTS.md`

## Regras Que Não Podem Ser Quebradas

- não alterar preços existentes sem pedido explícito
- não criar total nulo ou inconsistente
- não quebrar persistência do snapshot do pedido
- não remover observações existentes do item
- não alterar models nesta trilha sem necessidade explícita
- não esconder regra de cálculo dentro de texto de resposta
- documentar quando a mudança deveria futuramente nascer em um `OrderService` ou `ProductService`

## Checklist Antes da Alteração

1. localizar origem dos itens
2. localizar onde subtotal e total são calculados
3. revisar `_items_for_persistence`
4. revisar agrupamento e pluralização
5. identificar impacto em resumo final
6. separar mentalmente parsing de mensagem versus regra de negócio

## Checklist Depois da Alteração

1. validar total do pedido
2. validar resumo textual
3. validar persistência de itens
4. validar pedido com múltiplos itens
5. atualizar changelog
6. registrar se a regra deveria migrar futuramente para `services/`

## Testes Mínimos Recomendados

- item único
- múltiplos itens
- quantidade maior que 1
- item adicional/complemento
- total recalculado corretamente

## Exemplos de Prompts

- `Ajuste apenas a soma dos itens complementares, sem tocar no fluxo de pagamento.`
- `Inclua um novo tipo de item no pedido preservando persistência e resumo final.`
- `Revise por que o subtotal do item X não está sendo recalculado corretamente.`

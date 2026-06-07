# Skill 04 - Ajustar Cardápio e Estoque

## Objetivo

Orientar mudanças em produtos ativos, cardápio do dia, disponibilidade, bebidas, adicionais e sobremesas.

## Quando Usar

- alteração de listagem de produtos ativos
- ajuste de itens mostrados no cardápio
- revisão de filtros por categoria
- validação de disponibilidade sem preço

## Arquitetura Lógica a Respeitar

- `services/`
  é o lugar lógico principal para regras de produto, categorias, cardápio, bebidas, adicionais, sobremesas, disponibilidade e filtros de exibição.
- `agents/`
  devem apenas apresentar ou interpretar a escolha do cliente, não centralizar a regra comercial do catálogo.
- `conversation/`
  decide em qual etapa o cardápio ou complemento aparece, mas não define regra comercial de produto.
- `integrations/`
  só entram se a origem do cardápio ou estoque vier de API externa.
- `repositories/`
  devem ser considerados no futuro para consultas mais complexas de catálogo, estoque e disponibilidade.
- `tests/`
  devem validar listagem, ocultação, seleção e cálculo quando o item entra no fluxo.

Regra prática:

- categoria, ativo/inativo, preço válido, elegibilidade para lista e regra de exibição pertencem logicamente a `services/`
- se houver lookup mais sofisticado por banco ou integração, a camada futura correta é `repositories/`

## Arquivos Prováveis Envolvidos

- `app/order_catalog.py`
- `app/agents/order_agent.py`
- `app/agents/cardapio_agent.py`
- `app/models.py`
- `app/business_config.py`
- `app/tests/test_cardapio_day_context.py`
- `docs/PROJECT_MAP.md`

## Regras Que Não Podem Ser Quebradas

- não alterar preços sem solicitação explícita
- não mostrar automaticamente item ativo sem preço se o fluxo não souber tratar
- não misturar cardápio do dia com catálogo estrutural de pedidos
- não criar acoplamento entre disponibilidade de cardápio e pagamento
- não esconder regra comercial de produto apenas em texto de agente
- documentar quando a regra deveria migrar para `services/` ou `repositories/`

## Checklist Antes da Alteração

1. confirmar se a mudança é de catálogo estrutural ou cardápio do dia
2. identificar categoria do produto
3. revisar filtro de `disponivel`
4. revisar tratamento de preço nulo
5. revisar testes existentes de listagem
6. decidir se a mudança é regra de negócio ou só apresentação

## Checklist Depois da Alteração

1. validar lista exibida ao cliente
2. validar itens ocultos quando necessário
3. validar seleção por número e texto natural
4. validar total do pedido quando item entra no fluxo
5. atualizar changelog
6. registrar se o caso pede futura camada de `repositories/`

## Testes Mínimos Recomendados

- produto ativo com preço
- produto ativo sem preço
- produto indisponível
- seleção por número
- seleção por texto natural

## Exemplos de Prompts

- `Ajuste a lista de complementos para considerar apenas itens ativos com preço válido.`
- `Revise o filtro de bebidas e sobremesas sem mexer em pagamento ou horários.`
- `Adapte a leitura do cardápio do dia sem alterar o catálogo dos pedidos principais.`

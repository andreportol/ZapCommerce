# Skill 07 - Criar Testes de Conversa

## Objetivo

Orientar a criação de testes de conversa completa para fluxos de pedido, complementos, pagamento, horários e recuperação.

## Quando Usar

- criação de teste para novo passo conversacional
- cobertura de regressão em fluxo já existente
- validação de mensagens finais ao cliente

## Arquitetura Lógica a Respeitar

- `tests/`
  é o destino lógico principal desta skill. Toda alteração em fluxo precisa nascer acompanhada de validação em `tests/`.
- `conversation/`
  define o que precisa ser validado em transições de estado e sequência do fluxo.
- `agents/`
  influenciam interpretação de texto e decisões locais que precisam ser cobertas.
- `services/`
  influenciam totais, regras de produto, horários e pagamento que os testes devem congelar.
- `integrations/`
  devem ser isoladas ou simuladas quando necessário.
- `repositories/`
  devem ser abstraídos ou preparados para fixtures/fakes se surgirem no futuro.

Regra prática:

- toda alteração de fluxo precisa de teste em `tests/`
- isso inclui conversa completa, ambiguidade numérica, complementos, pagamento, comprovante e golden tests

## Arquivos Prováveis Envolvidos

- `app/tests/test_cardapio_day_context.py`
- `app/agents/orchestrator_agent.py`
- `app/agents/order_agent.py`
- `app/agents/message_agent.py`
- `docs/TEST_STRATEGY.md`

## Regras Que Não Podem Ser Quebradas

- não criar teste acoplado a detalhes desnecessários de implementação
- não esconder regressão real ajustando expectativa sem revisar o fluxo
- preferir cenários completos que reflitam conversa do cliente
- toda mudança em opções numéricas deve considerar teste de ambiguidade
- preferir cobertura funcional em `tests/` a asserts frágeis de implementação

## Checklist Antes da Alteração

1. localizar teste parecido
2. identificar estado inicial esperado
3. identificar mensagem do cliente e saída esperada
4. decidir se precisa fake de catálogo ou configuração
5. verificar se o teste deve cobrir texto natural e opção numérica
6. revisar `docs/TEST_STRATEGY.md`

## Checklist Depois da Alteração

1. rodar a suíte alvo
2. revisar nomes dos testes
3. revisar mensagens assertadas
4. revisar estado final assertado
5. atualizar changelog se a mudança for relevante
6. confirmar se há cobertura de conversa completa, ambiguidade numérica e regressão do passo seguinte

## Testes Mínimos Recomendados

- caminho feliz
- texto natural
- opção numérica
- continuação do fluxo
- não regressão do passo seguinte
- ambiguidade numérica
- golden test quando a etapa for crítica ou longa

## Exemplos de Prompts

- `Crie testes para esse novo passo do pedido usando o padrão existente em test_cardapio_day_context.py.`
- `Adicione um cenário de regressão para garantir que a resposta numérica não caia no menu principal.`
- `Cubra Pix, cartão e dinheiro sem alterar a lógica de produção.`

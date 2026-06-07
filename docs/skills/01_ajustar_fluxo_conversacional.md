# Skill 01 - Ajustar Fluxo Conversacional

## Objetivo

Orientar alterações no fluxo conversacional sem espalhar regras, sem quebrar retomada de conversa e sem alterar comportamentos não relacionados.

## Quando Usar

- mudança de ordem entre etapas da conversa
- inclusão de nova etapa no pedido
- ajuste de decisão entre menu, pedido, cardápio e atendimento humano
- revisão de fallback ou retomada

## Arquitetura Lógica a Respeitar

- `agents/`
  continuam sendo o lugar de interpretação da mensagem e decisão imediata do próximo passo.
- `conversation/`
  é o lugar lógico correto para regras de transição, encadeamento de etapas e definição formal do fluxo, mesmo que hoje isso ainda esteja concentrado em `app/agents/`.
- `services/`
  devem concentrar regras de negócio que o fluxo apenas consome.
- `integrations/`
  devem receber apenas integrações externas necessárias ao fluxo, não a regra de transição em si.
- `repositories/`
  devem ser considerados apenas se a alteração exigir acesso a dados mais complexo no futuro.
- `tests/`
  devem validar o fluxo completo e as ambiguidades introduzidas.

Regra prática:

- se a mudança for interpretação da resposta do cliente, ela nasce logicamente em `agents/`
- se a mudança for ordem entre etapas, condição de avanço, retorno ou bloqueio, ela pertence logicamente a `conversation/`
- enquanto a pasta física ainda não existir, documente a intenção e mantenha a alteração localizada nos arquivos atuais

## Arquivos Prováveis Envolvidos

- `app/agents/orchestrator_agent.py`
- `app/agents/order_agent.py`
- `app/agents/message_agent.py`
- `app/agents/conversation_state.py`
- `app/tests/test_cardapio_day_context.py`
- `docs/CONVERSATION_FLOW.md`
- `docs/STATE_MACHINE.md`

## Regras Que Não Podem Ser Quebradas

- não refatorar arquivos inteiros sem necessidade
- não alterar pagamento, Pix e comprovante se a tarefa não for disso
- não alterar horários se a tarefa não for disso
- não criar migration para ajuste conversacional
- não duplicar regra em múltiplos agentes sem necessidade
- não tratar regra de transição como detalhe textual de mensagem
- documentar a intenção de futura migração para `conversation/` quando a lógica ainda precisar ficar em `app/agents/`

## Checklist Antes da Alteração

1. ler `docs/PROJECT_MAP.md`
2. ler `docs/CONVERSATION_FLOW.md`
3. ler `docs/STATE_MACHINE.md`
4. localizar onde o fluxo atual entra e sai
5. identificar quais estados e esperas serão afetados
6. decidir o que é decisão de agente e o que é transição lógica de conversa
7. localizar os testes já existentes do caminho

## Checklist Depois da Alteração

1. confirmar que a conversa continua retomável
2. revisar mensagens intermediárias e finais
3. validar números de menu versus números de etapas internas
4. atualizar testes
5. atualizar `docs/CHANGELOG_IA.md`
6. registrar se a mudança deveria migrar futuramente para `conversation/`

## Testes Mínimos Recomendados

- início do fluxo alterado
- passo imediatamente anterior
- novo passo inserido ou alterado
- passo imediatamente posterior
- resposta por texto natural
- resposta numérica
- fallback e retomada

## Exemplos de Prompts

- `Ajuste apenas a etapa entre quantidade e entrega, sem alterar pagamento nem horários.`
- `Inclua uma nova pergunta no fluxo de pedido reutilizando os estados existentes quando possível.`
- `Revise por que a etapa X está pulando para Y e corrija sem refatorar o orquestrador inteiro.`

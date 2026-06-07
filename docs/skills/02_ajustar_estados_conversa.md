# Skill 02 - Ajustar Estados da Conversa

## Objetivo

Orientar alterações em `status_atendimento`, `aguardando_resposta`, retomada de conversa e integridade do estado persistido.

## Quando Usar

- criação de novo estado ou nova espera
- correção de transição de estado
- recuperação de contexto quebrado
- ajuste de retomada entre mensagens

## Arquitetura Lógica a Respeitar

- `conversation/`
  é o destino lógico principal desta skill. Estados, transições, validações de consistência e prompts de continuação devem ser pensados para uma futura migração para `conversation/states.py` e `conversation/transitions.py`.
- `agents/`
  continuam lendo e acionando estados no desenho atual, mas não devem concentrar permanentemente toda a semântica do fluxo.
- `services/`
  devem fornecer regras de negócio usadas pelas transições, sem virar depósito de estado conversacional.
- `integrations/`
  não devem receber estados de conversa, exceto dados estritamente necessários para comunicação externa.
- `repositories/`
  só entram se a persistência de estado ou lookup associado ficar mais complexa no futuro.
- `tests/`
  devem cobrir transição de entrada, saída e recuperação.

Regra prática:

- novo estado nasce conceitualmente em `conversation/`
- enquanto a estrutura física ainda estiver em `app/agents/`, manter o ajuste pequeno e documentado

## Arquivos Prováveis Envolvidos

- `app/agents/conversation_state.py`
- `app/agents/orchestrator_agent.py`
- `app/agents/order_agent.py`
- `app/agents/message_agent.py`
- `app/tests/test_cardapio_day_context.py`
- `docs/STATE_MACHINE.md`

## Regras Que Não Podem Ser Quebradas

- não deixar estado impossível sem tratamento
- não introduzir `aguardando_resposta` novo sem atualizar validações
- não quebrar `reset_state`, `update_state` e retomada por saudação
- não remover fallback de recuperação
- documentar o estado pensando em futura separação entre `states.py` e `transitions.py`

## Checklist Antes da Alteração

1. listar estado atual e estado desejado
2. localizar onde o estado é lido
3. localizar onde o estado é gravado
4. revisar `_invalid_state_reason`
5. revisar `_has_pending_order_step` e `_has_active_order_context`
6. revisar `docs/STATE_MACHINE.md`

## Checklist Depois da Alteração

1. revisar sanidade do novo estado
2. revisar prompt de continuação
3. revisar recuperação após erro
4. cobrir com testes de transição
5. atualizar `docs/CONVERSATION_FLOW.md` se o fluxo mudou
6. atualizar `docs/STATE_MACHINE.md` se houve novo estado, nova espera ou nova transição

## Testes Mínimos Recomendados

- entrada no novo estado
- saída correta do novo estado
- retomada após nova mensagem
- estado inválido recuperado
- cenário numérico e texto natural

## Exemplos de Prompts

- `Crie um novo aguardando_resposta para a etapa X e atualize somente os pontos necessários.`
- `Corrija a transição entre os estados A e B sem mexer no fluxo de pagamento.`
- `Mapeie onde esse estado precisa ser reconhecido no orquestrador e no message_agent.`

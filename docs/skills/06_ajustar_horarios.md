# Skill 06 - Ajustar Horários

## Objetivo

Orientar mudanças em horário de funcionamento, bloqueio fora do horário e mensagens de disponibilidade.

## Quando Usar

- ajuste de regra de pedidos fora do horário
- revisão de horários de entrega e retirada
- ajuste das mensagens que informam funcionamento

## Arquitetura Lógica a Respeitar

- `services/`
  é o lugar lógico principal para regras de horário, disponibilidade, janelas de pedido, entrega e retirada.
- `conversation/`
  é o lugar lógico para a decisão de bloquear, continuar, retomar ou redirecionar o fluxo com base nessas regras.
- `agents/`
  interpretam a pergunta do cliente e aplicam a decisão conversacional já definida.
- `integrations/`
  só entram se a fonte do horário vier de serviço externo.
- `repositories/`
  podem ser considerados no futuro se a leitura de agenda ou configuração ficar mais complexa.
- `tests/`
  devem validar dentro do horário, fora do horário e respostas paralelas informativas.

Regra prática:

- a regra “está aberto ou fechado” pertence logicamente a `services/`
- a decisão “bloqueia pedido, informa horário ou retoma fluxo” pertence logicamente a `conversation/` e `agents/`

## Arquivos Prováveis Envolvidos

- `app/business_config.py`
- `app/agents/orchestrator_agent.py`
- `app/agents/instructions_agent.py`
- `app/tests/test_cardapio_day_context.py`
- `docs/STATE_MACHINE.md`

## Regras Que Não Podem Ser Quebradas

- não permitir pedidos fora do horário se a regra continuar ativa
- não duplicar regras de janela em múltiplos arquivos
- não alterar pagamento ou catálogo ao mexer em horário
- não quebrar respostas informativas fora do horário
- não esconder regra de disponibilidade apenas em texto de resposta
- manter a fonte de verdade do horário em regra de negócio, não em mensagem

## Checklist Antes da Alteração

1. identificar se a mudança é de configuração ou de mensagem
2. revisar `is_open_for_orders`
3. revisar respostas fora do horário no orquestrador
4. revisar horário de entrega e retirada
5. localizar testes atuais de bloqueio
6. separar regra de disponibilidade versus decisão de fluxo

## Checklist Depois da Alteração

1. validar pedido dentro do horário
2. validar pedido fora do horário
3. validar dúvida sobre entrega fora do horário
4. validar cardápio fora do horário
5. atualizar changelog
6. registrar se a mudança deveria futuramente sair de `agents/` para `services/` ou `conversation/`

## Testes Mínimos Recomendados

- saudação fora do horário
- tentativa de pedido fora do horário
- consulta de horários
- consulta de entrega
- resposta curta após repetição fora do horário

## Exemplos de Prompts

- `Ajuste apenas a mensagem de fora do horário, sem mexer na regra de bloqueio.`
- `Revise o resumo de horários de entrega e retirada usando business_config.py como fonte única.`
- `Corrija um falso bloqueio de pedido dentro do horário atual.`

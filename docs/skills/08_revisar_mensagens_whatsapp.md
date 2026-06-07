# Skill 08 - Revisar Mensagens WhatsApp

## Objetivo

Orientar revisão de mensagens enviadas ao cliente para manter tom natural, educado, objetivo e consistente com o fluxo real.

## Quando Usar

- ajuste de texto exibido ao cliente
- revisão de clareza em perguntas
- padronização de mensagens de pedido, pagamento e fallback

## Arquitetura Lógica a Respeitar

- `agents/`
  continuam sendo a camada natural para texto de resposta e formulação de perguntas ao cliente.
- `conversation/`
  define o contexto e a etapa em que a mensagem aparece.
- `services/`
  devem conter a regra de negócio real que a mensagem apenas comunica.
- `integrations/`
  cuidam do canal externo, mas não devem decidir o conteúdo de negócio da mensagem.
- `repositories/`
  não são lugar para regra textual.
- `tests/`
  devem validar que a mensagem continua coerente com o comportamento real.

Regra prática:

- texto pode continuar na camada de `agents/`
- regra de negócio não deve ficar escondida dentro de uma mensagem, string ou copy
- se mudar o texto porque a regra mudou, a regra precisa estar representada no local conceitual correto

## Arquivos Prováveis Envolvidos

- `app/agents/order_agent.py`
- `app/agents/orchestrator_agent.py`
- `app/services.py`
- `app/tests/test_cardapio_day_context.py`
- `docs/CONVERSATION_FLOW.md`
- `docs/CONTRACTS.md`

## Regras Que Não Podem Ser Quebradas

- não alterar significado funcional da etapa
- não prometer ação que o sistema não executa
- não confirmar pagamento automaticamente
- não soar ríspido, robótico ou excessivamente longo
- não usar mensagem para mascarar ausência de regra de negócio correta
- não mover decisão funcional para dentro do texto

## Checklist Antes da Alteração

1. identificar em que etapa a mensagem aparece
2. verificar o estado correspondente
3. confirmar se existe teste textual para ela
4. checar se a mensagem informa exatamente o que o sistema faz
5. confirmar onde a regra real da etapa deveria morar: `agents/`, `conversation/` ou `services/`

## Checklist Depois da Alteração

1. revisar clareza da mensagem
2. revisar consistência com o fluxo
3. revisar se a etapa seguinte continua evidente
4. atualizar testes textuais se necessário
5. atualizar changelog
6. confirmar que nenhuma regra de negócio ficou escondida na copy

## Testes Mínimos Recomendados

- mensagem principal da etapa
- mensagem de continuação
- mensagem de fallback
- mensagem com resposta numérica

## Exemplos de Prompts

- `Revise apenas o texto enviado ao cliente nessa etapa, sem alterar a lógica.`
- `Deixe a mensagem mais natural no WhatsApp, mantendo o mesmo comportamento funcional.`
- `Simplifique essa pergunta sem mudar a ordem do fluxo nem os estados.`

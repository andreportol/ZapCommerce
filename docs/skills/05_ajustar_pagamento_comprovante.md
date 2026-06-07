# Skill 05 - Ajustar Pagamento e Comprovante

## Objetivo

Orientar mudanças em Pix, dinheiro, cartão, instruções de pagamento, comprovante e conferência manual.

## Quando Usar

- ajuste de mensagens de pagamento
- revisão de escolha de Pix, dinheiro ou cartão
- mudança de comportamento na etapa de comprovante
- reforço de conferência manual

## Arquitetura Lógica a Respeitar

- `services/`
  é o lugar lógico principal para regras internas de Pix, dinheiro, cartão, conferência esperada, resumo financeiro e decisões de negócio ligadas ao pagamento.
- `integrations/`
  é o lugar lógico correto quando a mudança envolver API externa, gateway, Asaas, Meta, e-mail ou envio/recebimento externo.
- `agents/`
  devem apenas interpretar a resposta do cliente e chamar a regra de pagamento adequada.
- `conversation/`
  controla a etapa do fluxo em que o pagamento ou comprovante acontece, sem carregar toda a regra financeira.
- `repositories/`
  podem ser úteis no futuro se houver rastreamento mais complexo de comprovantes ou transações.
- `tests/`
  devem garantir que Pix, dinheiro, cartão e comprovante não regrediram.

Regra prática:

- se for regra interna de pagamento, pertence logicamente a `services/`
- se for integração com API ou envio externo, pertence logicamente a `integrations/`

## Arquivos Prováveis Envolvidos

- `app/agents/order_agent.py`
- `app/agents/payment_proof_agent.py`
- `app/models.py`
- `app/services.py`
- `app/tests/test_cardapio_day_context.py`
- `docs/CONTRACTS.md`

## Regras Que Não Podem Ser Quebradas

- não confirmar pagamento Pix automaticamente
- não pular a etapa de comprovante quando Pix exigir conferência
- não alterar fluxo de pedido se a mudança for só de pagamento
- não expor segredos ou credenciais
- não esconder regra financeira dentro de texto ou fallback de mensagem
- separar claramente regra interna de pagamento de integração externa

## Checklist Antes da Alteração

1. identificar forma de pagamento afetada
2. revisar transição para comprovante ou confirmação
3. revisar resumo final do pedido
4. revisar mensagens de segurança do Pix
5. revisar testes existentes de comprovante
6. decidir se a mudança é de `services/` ou `integrations/`

## Checklist Depois da Alteração

1. validar Pix
2. validar dinheiro
3. validar cartão
4. validar comprovante e conferência
5. atualizar changelog
6. registrar se a responsabilidade futura correta é `services/` ou `integrations/`

## Testes Mínimos Recomendados

- escolha de Pix
- envio de comprovante
- conferência pendente
- escolha de dinheiro
- escolha de cartão
- confirmação final sem Pix

## Exemplos de Prompts

- `Ajuste apenas a mensagem da etapa Pix sem alterar o comportamento de conferência.`
- `Revise a detecção de comprovante preservando a regra de revisão manual.`
- `Inclua validação extra para pagamento em dinheiro sem mexer nos demais meios.`

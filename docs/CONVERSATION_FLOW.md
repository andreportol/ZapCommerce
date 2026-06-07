# Conversation Flow

## Fluxo Conversacional Oficial

Este documento descreve o fluxo conversacional oficial atual da Marmitaria IA. Ele deve ser tratado como referência funcional antes de alterar agentes, estados ou mensagens.

## Menu Inicial

Entrada padrão:

1. Fazer pedido
2. Saber o cardápio
3. Mais informações
4. Falar com a atendente

Também existem respostas de recuperação quando o orquestrador detecta estado inválido ou falha no fluxo.

## Pedido

Fluxo base:

1. cliente inicia pedido
2. bot oferece opções principais de marmita/marmitex
3. cliente informa item e quantidade
4. sistema calcula subtotal do pedido principal

## Escolha de Produto

Produtos principais são resolvidos a partir de `app/order_catalog.py` e regras de parsing em `app/agents/order_agent.py`.

Produtos principais atuais:

- Marmitex individual
- Marmita para 2 pessoas
- Marmita para 3 pessoas
- Marmita para 4 pessoas
- Marmita para 5 pessoas

## Quantidade

- marmitex individual normalmente exige quantidade explícita
- marmitas familiares podem depender do tamanho escolhido
- pedidos acima do limite de consulta exigem encaminhamento para confirmação da proprietária

## Complementos

Depois do produto principal e da quantidade:

1. o bot mostra resumo parcial
2. o sistema busca complementos ativos das categorias `Bebida`, `Adicional` e `Sobremesa`
3. itens sem preço válido não entram automaticamente na lista
4. o cliente pode escolher por número ou texto natural
5. o bot pergunta quantidade quando necessário
6. o total é recalculado
7. o bot pergunta se deseja adicionar mais itens
8. só depois segue para entrega/retirada

## Entrega ou Retirada

Após encerrar complementos:

1. bot pergunta `Entrega` ou `Retirada no local`
2. a resposta pode vir por número ou linguagem natural
3. o fluxo deve respeitar o que estiver habilitado em `ConfiguracaoMarmitaria`

## Nome e Endereço

- se for entrega:
  primeiro endereço, depois nome
- se for retirada:
  vai direto para o nome

O nome do cliente é persistido no cadastro quando válido.

## Pagamento

Formas de pagamento atuais:

1. Pix
2. Dinheiro
3. Cartão

Após coletar a forma de pagamento, o sistema monta o resumo final e pede confirmação quando aplicável.

## Pix

Quando o cliente escolhe Pix:

1. o bot envia valor do pedido
2. o bot envia chave Pix e favorecido
3. o sistema orienta o envio do comprovante

Não há confirmação automática do pagamento.

## Comprovante

O sistema aceita sinais de comprovante por:

- texto
- imagem
- PDF

O `PaymentProofAgent` apenas identifica que um comprovante foi enviado e marca a etapa para conferência.

## Conferência

Depois do envio do comprovante:

1. o estado muda para conferência
2. o cliente é informado de que a validação depende da equipe
3. o sistema não deve afirmar que o Pix foi confirmado automaticamente

## Atendimento Humano

O atendimento pode ser encaminhado para humano quando:

- o cliente pede atendente
- o fluxo exige consulta da proprietária
- o sistema produz uma resposta que indica encaminhamento humano

O status da conversa pode migrar para `HUMANO`.

## Horários

O fluxo de pedido respeita as janelas de:

- pedidos/encomendas
- entregas
- retiradas

As regras de horário ficam em `app/business_config.py` e são aplicadas principalmente no `OrchestratorAgent`.

Quando fora do horário:

- o sistema bloqueia novos pedidos
- ainda pode responder informações básicas
- o texto deve deixar claro o horário válido de atendimento

## Arquivos-Chave Do Fluxo

- `app/agents/orchestrator_agent.py`
- `app/agents/order_agent.py`
- `app/agents/conversation_state.py`
- `app/agents/payment_proof_agent.py`
- `app/business_config.py`
- `app/order_catalog.py`

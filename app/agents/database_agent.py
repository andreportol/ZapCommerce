class DatabaseAgent:
    """
    Estrutura inicial para consultas futuras de banco.
    Nesta etapa nao executa consultas reais.
    """

    def get_order_status(self, _query: str) -> dict:
        return {
            "implemented": False,
            "message": "Consulta de pedido ainda nao implementada nesta etapa.",
            "data": None,
        }

    def get_payment_status(self, _query: str) -> dict:
        return {
            "implemented": False,
            "message": "Consulta de pagamento ainda nao implementada nesta etapa.",
            "data": None,
        }

    def general_lookup(self, _query: str) -> dict:
        return {
            "implemented": False,
            "message": "Consulta geral ao banco ainda nao implementada nesta etapa.",
            "data": None,
        }

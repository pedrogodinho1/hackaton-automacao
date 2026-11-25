# Recria as tabelas de referencia no SQLite local e cadastra as leis e parametros padrao
from app.seed import (
    obter_pontos_coleta,
    obter_legislacoes,
    obter_limites_legais,
    garantir_banco_referencia,
)


def inicializar_banco(recriar=True):
    """Recria as tabelas do zero e insere os pontos de coleta, normas e limites legais."""
    garantir_banco_referencia(recriar=recriar, verboso=True)


if __name__ == '__main__':
    inicializar_banco(recriar=True)

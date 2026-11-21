"""
Ponto de entrada (Entry Point) da aplicação web.

Responsabilidade:
- Importa a instância configurada do Flask ('app') do pacote 'app'.
- Inicializa o servidor HTTP de desenvolvimento local.
- O modo debug (`debug=True`) ativa o recarregamento automático do servidor
  a cada alteração nos arquivos de código e exibe o depurador interativo no terminal/navegador.
"""

from app import app

if __name__ == '__main__':
    app.run(debug=True)

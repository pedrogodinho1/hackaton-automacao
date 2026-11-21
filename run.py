# Inicia o servidor local em modo debug (recarrega o app ao salvar alteracoes)
from app import app

if __name__ == '__main__':
    app.run(debug=True)

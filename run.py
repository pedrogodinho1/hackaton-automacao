# Inicia o servidor local (controle o modo debug pela variavel FLASK_DEBUG no .env)
import os
from app import app

if __name__ == '__main__':
    debug_ativo = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='127.0.0.1', port=5000, debug=debug_ativo)

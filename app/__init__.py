# Crie e configure a aplicação Flask

from flask import Flask

app = Flask(__name__)

# Importa as rotas depois de criar o app para evitar erros de referência circular
from app import routes
# Recebe o arquivo Excel do usuário e devolve a página de resposta

from app import app

@app.route('/')
def index():
    return "Servidor Flask rodando com sucesso!"
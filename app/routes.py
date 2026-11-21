"""
Camada de Rotas e Controladores (Controller) da aplicação.

Responsabilidade:
- Mapeia as URLs e métodos HTTP (GET, POST) para funções de visualização.
- Recebe arquivos de laudos laboratoriais enviados pelo usuário (planilhas Excel / relatórios PDF).
- Repassa os dados para a camada de serviço ('services.py') para validação e cálculos matemáticos.
- Renderiza os templates HTML com os resultados analíticos, alertas de não conformidade e eficiências calculadas.
"""

from app import app

@app.route('/')
def index():
    """
    Rota principal da aplicação (GET /).
    Apresenta a interface inicial com o formulário de upload de arquivos de monitoramento.
    """
    return "Servidor Flask rodando com sucesso!"

# Arquivo principal que liga o servidor web

from app import app

if __name__ == '__main__':
    # debug=True permite que o servidor reinicie automaticamente quando alterações são feitas no código
    app.run(debug=True)
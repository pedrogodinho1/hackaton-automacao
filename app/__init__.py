"""
Fábrica de inicialização e configuração central da aplicação Flask.

Responsabilidades:
1. Instanciar o aplicativo Flask principal.
2. Definir os caminhos de armazenamento e persistência:
   - Utiliza a pasta 'instance/' para abrigar o banco de dados SQLite ('monitoramento.db').
   - Manter o banco em 'instance/' isola o estado mutável do código-fonte do projeto,
     garantindo que o banco não seja versionado no repositório Git.
3. Configurar chaves de segurança e o ORM SQLAlchemy:
   - 'SECRET_KEY': Utilizada para criptografar sessões de usuário e tokens CSRF de formulários.
   - 'SQLALCHEMY_DATABASE_URI': Define a string de conexão apontando para o SQLite local.
   - 'SQLALCHEMY_TRACK_MODIFICATIONS': Definido como False para desativar o monitoramento
     de eventos do SQLAlchemy, reduzindo overhead de memória e melhorando a performance.
4. Inicializar o objeto 'db' (instância do SQLAlchemy), que orquestra as conexões e transações.
5. Importar modelos e rotas no final do arquivo:
   - A ordem de importação ao final é mandatória para evitar referências circulares
     (circular imports), garantindo que as instâncias 'app' e 'db' já existam quando os
     módulos de rotas e modelos forem carregados.
"""

import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# Resolução de caminhos do projeto e diretório de instância
basedir = os.path.abspath(os.path.dirname(__file__))
project_dir = os.path.dirname(basedir)
instance_dir = os.path.join(project_dir, 'instance')
os.makedirs(instance_dir, exist_ok=True)

# Configurações do servidor e banco de dados
app.config['SECRET_KEY'] = 'dev-secret-key-hackathon-evonik-etec'
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(instance_dir, 'monitoramento.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Instância global do ORM para comunicação com o SQLite
db = SQLAlchemy(app)

# Importação de modelos (tabelas) e controladores (rotas HTTP) após a instanciação do 'app' e 'db'
from app import models, routes

import os
from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

app = Flask(__name__)

# Guarda o SQLite dentro da pasta instance/ para nao versionar dados locais no git
basedir = os.path.abspath(os.path.dirname(__file__))
project_dir = os.path.dirname(basedir)
instance_dir = os.path.join(project_dir, 'instance')
os.makedirs(instance_dir, exist_ok=True)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-hackathon-evonik-etec')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'SQLALCHEMY_DATABASE_URI',
    f"sqlite:///{os.path.join(instance_dir, 'monitoramento.db')}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Rotas e modelos precisam vir no final para evitar erro de import circular no Flask
from app import models, routes

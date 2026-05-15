import os
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'una_clave_muy_segura'
    # Configuración de base de datos
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'instance', 'turnos.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

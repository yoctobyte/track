import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'super-secret-key-for-dev'
    DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app', 'data')
    DEVICES_FILE = os.path.join(DATA_DIR, 'devices.json')
    LOGS_FILE = os.path.join(DATA_DIR, 'logs.json')
    AUTH_FILE = os.path.join(DATA_DIR, 'auth.json')
    CONFIG_JSON = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'config.json')

import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(24).hex()
    DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app', 'data')
    DEVICES_FILE = os.path.join(DATA_DIR, 'devices.json')
    LOGS_FILE = os.path.join(DATA_DIR, 'logs.json')
    AUTH_FILE = os.path.join(DATA_DIR, 'auth.json')
    CONFIG_JSON = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'config.json')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB maximum payload size

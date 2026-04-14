import json
import os
from app import app

if __name__ == '__main__':
    port = 4575
    bind = '0.0.0.0'
    config_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'config.json')
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                cfg = json.load(f)
                port = cfg.get('port', port)
                bind = cfg.get('bind', bind)
        except Exception:
            pass
            
    app.run(host=bind, port=port, debug=False)

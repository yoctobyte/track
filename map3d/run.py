#!/usr/bin/env python3
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    ssl_mode = os.environ.get("MAP3D_SSL", "adhoc")
    app.run(
        debug=False,
        host=os.environ.get("MAP3D_HOST", "0.0.0.0"),
        port=int(os.environ.get("MAP3D_PORT", "5000")),
        ssl_context=None if ssl_mode == "off" else ssl_mode,
    )

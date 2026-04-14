#!/usr/bin/env python3

from app import app


if __name__ == "__main__":
    cfg = app.config["TRACKHUB"]
    app.run(host=cfg["bind"], port=cfg["port"], debug=False)

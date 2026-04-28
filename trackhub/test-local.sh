#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/venv"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q -r "$DIR/requirements.txt"

"$VENV/bin/python" -m json.tool "$DIR/config.json" >/dev/null
"$VENV/bin/python" -m json.tool "$DIR/config.example.json" >/dev/null
"$VENV/bin/python" -m py_compile "$DIR/app.py" "$DIR/config.py" "$DIR/tests_local.py"
"$VENV/bin/python" "$DIR/tests_local.py"

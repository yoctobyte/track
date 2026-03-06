#!/bin/bash
# Museum Kiosk Control Application Runner

# Change to the directory where the script is located
cd "$(dirname "$0")"

# Set the port dynamically from config.json (fallback to 4575)
PORT=$(python3 -c "import json; print(json.load(open('config.json')).get('port', 4575))" 2>/dev/null || echo 4575)

# Kill any existing instance running on this port or script
echo "Killing any existing instances of the app..."
pkill -f "python run.py" || true
fuser -k $PORT/tcp || true

# Setup Python virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install or update requirements
echo "Checking requirements..."
pip install -r requirements.txt

# Export necessary environment variables
export FLASK_APP=run.py
export FLASK_ENV=production
# Setup stable secret key if it doesn't exist
if [ ! -f ".secret_key" ]; then
    echo "museum-kiosk-secret-key-$(date +%s)-$(openssl rand -hex 12)" > .secret_key
fi
export SECRET_KEY=$(cat .secret_key)

# Start the application
echo "Starting Museum Kiosk Control app on port $PORT..."
nohup python run.py > app.log 2>&1 &
PID=$!

echo "Application started with PID $PID. Logs can be found in app.log."

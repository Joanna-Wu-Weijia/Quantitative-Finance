#!/bin/bash

APP_FILE="server_api.py"
LOG_FILE="server_api.log"
PID_FILE="server_api.pid"

echo "[*] Starting Quant Signal Server..."

# Check if process is already running
if [ -f "$PID_FILE" ]; then
    if ps -p $(cat "$PID_FILE") > /dev/null 2>&1; then
        echo "[-] Error: Server already running (PID: $(cat $PID_FILE))."
        echo "[-] Aborting. Please kill the process first."
        exit 1
    else
        echo "[-] Stale PID file found. Removing..."
        rm "$PID_FILE"
    fi
fi

# Launch in background
echo "[*] Launching $APP_FILE in background..."
nohup python -u $APP_FILE > $LOG_FILE 2>&1 &

# Save PID
echo $! > $PID_FILE

# Output status
echo "[+] Server started."
echo "[+] PID  : $(cat $PID_FILE)"
echo "[+] Logs : tail -f $LOG_FILE"
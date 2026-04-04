#!/bin/sh

touch $HOME/.miner-uvicorn.log
LOG_FILE="${LOG_FILE:-$HOME/.miner-uvicorn.log}"
touch "$LOG_FILE"
tail -f $HOME/.miner-uvicorn.log &

# Use info in prod to avoid WebSocket ping/pong debug flood and reduce log I/O (debug can contribute to OOM under load)
uvicorn --host 0.0.0.0 --port 8888 --uds /tmp/unicorn.sock --access-log --log-level info minerservice.main:app >> "$LOG_FILE" 2>&1

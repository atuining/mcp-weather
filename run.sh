#!/usr/bin/env bash

echo "===== Activating virtual environment ====="
source venv/bin/activate

echo "===== Starting the mcp server ====="
exec python3 weather.py

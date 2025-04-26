#!/usr/bin/env bash

set -e

echo "===== Verifying Python version ====="
python3 -c 'import sys; version = sys.version_info; assert version >= (3,10), f"Python 3.10 or above is required, for {version}"' || { echo "Python version check failed"; exit 1; }

echo "===== Creating virtual environment ====="
python3 -m venv venv

echo "===== Activating virtual environment ====="
source venv/bin/activate

echo "===== Upgrading pip ====="
pip install --upgrade pip

echo "===== Installing dependencies ====="
pip install -r requirements.txt

echo "===== Build Complete ====="

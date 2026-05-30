#!/bin/bash
set -e

cd /home/runner/workspace/bot

echo "=== VFS Italy Monitor Bot ==="
echo "Installing dependencies..."
pip install -r requirements.txt -q

echo "Installing Playwright browsers..."
playwright install chromium --with-deps 2>/dev/null || echo "Playwright chromium install skipped (may already be installed)"

echo "Starting bot..."
python main.py

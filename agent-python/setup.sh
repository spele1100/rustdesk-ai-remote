#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "🔧 Setting up AI Remote Desktop Agent..."

# Create venv if not exists
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo ""
echo "🚀 Starting agent..."
python agent.py "$@"

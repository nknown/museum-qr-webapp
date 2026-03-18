#!/bin/bash

python3.11 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip setuptools wheel

pip install -r requirements.lock.txt

cp .env.example .env 2>/dev/null || true

echo "✅ Project ready. Run:"
echo "source .venv/bin/activate && daphne freeweb.asgi:application"

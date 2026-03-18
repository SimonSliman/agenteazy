#!/usr/bin/env bash
GATEWAY="https://simondusable--agenteazy-gateway-serve.modal.run"
REGISTRY="https://simondusable--agenteazy-registry-serve.modal.run"

echo "1. Registry..."
curl -s --max-time 15 "$REGISTRY/agents" | python3 -m json.tool | head -5

echo ""
echo "2. Gateway DO verb (zxcvbn-python)..."
curl -s --max-time 30 -X POST "$GATEWAY/agent/zxcvbn-python/" \
  -H "Content-Type: application/json" \
  -d '{"verb":"DO","payload":{"data":{"password":"monkey123"}}}' | python3 -m json.tool

echo ""
echo "3. langdetect..."
curl -s --max-time 30 -X POST "$GATEWAY/agent/langdetect/" \
  -H "Content-Type: application/json" \
  -d '{"verb":"DO","payload":{"data":{"text":"Bonjour le monde"}}}' | python3 -m json.tool

echo ""
echo "4. pip install check..."
pip install agenteazy==0.2.7 --dry-run 2>&1 | head -3

#!/usr/bin/env bash
set -euo pipefail

# WSL2 or Linux only. For Windows native, use WSL.
# 1) Python venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip wheel
pip install -r requirements.txt

# 2) Node + Playwright MCP server
# Requires Node 18+
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required. Install Node 18+ first." >&2
  exit 1
fi
npm -g ls @executeautomation/playwright-mcp-server >/dev/null 2>&1 || npm -g install @executeautomation/playwright-mcp-server

# 3) Ollama
if ! command -v ollama >/dev/null 2>&1; then
  echo "Install Ollama from https://ollama.com/download" >&2
  exit 1
fi
# Expose API on all interfaces if needed
export OLLAMA_HOST=${OLLAMA_HOST:-0.0.0.0:11434}

# Pull models
# Main LLM (user-specified): Dolphin3.0-R1-Mistral-24B Q4_K_M from Hugging Face via Ollama
ollama run hf.co/mradermacher/Dolphin3.0-R1-Mistral-24B-GGUF:Q4_K_M <<<'exit' || true

# Optional vision model for screenshot parsing
ollama run llama3.2-vision <<<'exit' || true

# 4) Playwright browsers
npx -y playwright install chromium

# 5) Copy env
[ -f .env ] || cp .env.example .env

echo "setup done"
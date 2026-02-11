#!/usr/bin/env bash
set -euo pipefail

if ! python -m py_compile bot.py; then
  echo "❌ bot.py failed syntax compile. Showing first 80 lines for quick debug:"
  nl -ba bot.py | sed -n '1,80p' || true
  exit 1
fi

echo "✅ bot.py syntax check passed. Starting bot..."
exec python bot.py

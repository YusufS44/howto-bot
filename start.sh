#!/usr/bin/env bash
set -euo pipefail
set -x

# Add the current directory to Python path
export PYTHONPATH="/app:${PYTHONPATH:-}"

# Preflight: check if we can import (but don't fail immediately)
echo "=== Preflight Checks ==="
python -c "import sys,os; print('[python]', sys.version); print('[pwd]', os.getcwd()); print('[pythonpath]', os.environ.get('PYTHONPATH', ''))" || true

# Try import but continue even if it fails (for debugging)
python -c "\
try:\n\
    import server.app\n\
    print('[import] server.app: SUCCESS')\n\
    print('[app]', hasattr(server.app, 'app'))\n\
except Exception as e:\n\
    print('[import] server.app: FAILED -', e)\n\
" || true

# Show directory structure for debugging
echo "=== Directory Structure ==="
ls -la /app/ || true
ls -la /app/server/ || true
[ -d "/app/templates" ] && ls -la /app/templates/ || echo "No templates directory"

# Check if requirements are installed
echo "=== Installed Packages ==="
pip list | grep -E "(fastapi|uvicorn|jinja2)" || true

# Start FastAPI (use Cloud Run's PORT)
echo "=== Starting Server on PORT ${PORT:-8080} ==="
exec python -m uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8080} --log-level debug
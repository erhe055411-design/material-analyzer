#!/bin/bash
# Windows 用户启动脚本 (Git Bash / WSL)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

python3 -c "from models import init_db; init_db()" 2>/dev/null || python -c "from models import init_db; init_db()"
python3 app.py 2>/dev/null || python app.py

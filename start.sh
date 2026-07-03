#!/bin/bash
# 素材经营分析系统 - 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo "  素材经营分析系统 - Material Analyzer"
echo "============================================"
echo ""

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3，请先安装 Python 3.8+"
    exit 1
fi

echo "✅ Python3: $(python3 --version)"

# 检查依赖
if ! python3 -c "import flask" &> /dev/null; then
    echo "📦 安装依赖..."
    pip3 install -r requirements.txt
fi

echo "✅ 依赖检查完成"
echo ""

# 初始化数据库
python3 -c "from models import init_db; init_db()"
echo "✅ 数据库就绪"
echo ""

# 启动服务
echo "🚀 启动服务..."
echo ""
echo "  访问地址: http://localhost:8080"
echo ""
echo "  按 Ctrl+C 停止服务"
echo ""

python3 app.py

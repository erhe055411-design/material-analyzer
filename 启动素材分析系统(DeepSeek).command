#!/bin/bash
# 素材分析系统 - 一键更新DeepSeek配置并重启

PROJECT_DIR="/Users/test/Desktop/巨量ai工作引擎/material-analyzer"
ENV_FILE="$PROJECT_DIR/.env"

echo "🔄 正在更新 AI 配置..."

# 写入 DeepSeek 配置
cat > "$ENV_FILE" << 'EOF'
AI_API_KEY=sk-9848ab92faa94712ad9a55d12691a514
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
AI_TIMEOUT=30
EOF

echo "✅ .env 已更新为 DeepSeek 配置"

# 停止旧服务
echo "🛑 正在停止旧服务..."
OLD_PID=$(lsof -t -i :8080 2>/dev/null)
if [ -n "$OLD_PID" ]; then
    kill -9 $OLD_PID 2>/dev/null
    echo "   已停止进程 PID: $OLD_PID"
    sleep 1
else
    echo "   未发现旧进程"
fi

# 启动新服务
echo "🚀 正在启动素材分析系统..."
cd "$PROJECT_DIR"
nohup python3 app.py > /tmp/flask.log 2>&1 &
sleep 3

NEW_PID=$(lsof -t -i :8080 2>/dev/null)
if [ -n "$NEW_PID" ]; then
    echo ""
    echo "✅ 服务已启动！"
    echo "   PID: $NEW_PID"
    echo "   地址: http://localhost:8080"
    echo ""
    echo "📋 最新日志:"
    tail -n 5 /tmp/flask.log
    echo ""
    echo "🌐 请在浏览器中访问 http://localhost:8080"
    echo "   然后进入素材分析页面测试「✨ AI深度分析」"
else
    echo "❌ 启动失败，请检查日志: tail -f /tmp/flask.log"
fi

# 保持窗口打开
read -p "按回车键关闭此窗口..."

#!/bin/bash
# 一键修复AI配置并重启服务

DIR="/Users/test/Desktop/巨量ai工作引擎/material-analyzer"
ENV="$DIR/.env"

echo "🔧 正在修复AI配置..."

# 写入DeepSeek配置
printf '%s\n' \
    'AI_API_KEY=sk-9848ab92faa94712ad9a55d12691a514' \
    'AI_BASE_URL=https://api.deepseek.com/v1' \
    'AI_MODEL=deepseek-chat' \
    'AI_TIMEOUT=30' > "$ENV"

echo "✅ .env 已更新为 DeepSeek"

# 停止旧服务
echo "🛑 停止旧服务..."
PID=$(lsof -t -i :8080 2>/dev/null)
[ -n "$PID" ] && kill -9 $PID 2>/dev/null && echo "   已停止 PID $PID" || echo "   无旧进程"
sleep 1

# 启动
echo "🚀 启动服务..."
cd "$DIR"
nohup python3 app.py > /tmp/flask.log 2>&1 &
sleep 3

NEW=$(lsof -t -i :8080 2>/dev/null)
if [ -n "$NEW" ]; then
    echo ""
    echo "✅ 服务已启动！"
    echo "   PID: $NEW"
    echo "   地址: http://localhost:8080"
    tail -n 3 /tmp/flask.log
else
    echo "❌ 启动失败"
    tail -n 10 /tmp/flask.log
fi

read -p "按回车关闭..."

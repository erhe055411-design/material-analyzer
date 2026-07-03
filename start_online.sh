#!/bin/bash
# 素材经营分析系统 - 一键启动（本地+外网访问）

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 检查Python服务是否已在运行
PORT_PID=$(lsof -ti:8080 2>/dev/null)
if [ -n "$PORT_PID" ]; then
    echo "⚠️  端口8080已被占用，正在关闭旧服务..."
    kill -9 $PORT_PID 2>/dev/null
    sleep 1
fi

echo "=========================================="
echo "  🚀 正在启动素材经营分析系统..."
echo "=========================================="
echo ""

# 启动Flask服务（后台）
nohup python3 app.py > /tmp/flask_app.log 2>&1 &
FLASK_PID=$!
sleep 2

# 检查服务是否成功启动
if ! lsof -ti:8080 > /dev/null 2>&1; then
    echo "❌ Flask服务启动失败，请检查日志："
    cat /tmp/flask_app.log
    exit 1
fi

# 获取局域网IP
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)

echo "  ✅ 本地服务已启动！"
echo ""
echo "  📱 本机访问:     http://localhost:8080"
echo "  🌐 局域网访问:   http://${LAN_IP}:8080"
echo ""

# 启动Cloudflare隧道（外网访问）
CLOUDFLARED="/tmp/cloudflared"
if [ -f "$CLOUDFLARED" ]; then
    echo "  🌍 正在创建外网访问链接..."
    echo ""
    
    # 后台启动隧道
    nohup "$CLOUDFLARED" tunnel --url http://localhost:8080 > /tmp/cloudflared.log 2>&1 &
    TUNNEL_PID=$!
    
    # 等待隧道生成链接
    echo "  ⏳ 等待外网链接生成（约10-15秒）..."
    sleep 8
    
    # 从日志中提取链接
    TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' /tmp/cloudflared.log | head -1)
    
    if [ -n "$TUNNEL_URL" ]; then
        echo ""
        echo "=========================================="
        echo "  🎉 外网访问链接已生成！"
        echo "=========================================="
        echo ""
        echo "  🔗 ${TUNNEL_URL}"
        echo ""
        echo "  💡 任何人都可以通过上方链接访问系统"
        echo "  📋 可复制链接分享给同事/客户"
        echo ""
        echo "=========================================="
        echo "  ⚠️  安全提示："
        echo "  • 外网链接会随服务关闭失效"
        echo "  • 不要在公共网络分享敏感数据"
        echo "  • 关闭窗口即停止外网访问"
        echo "=========================================="
    else
        echo "  ⚠️  外网链接生成中，请稍候..."
        echo "  日志文件: /tmp/cloudflared.log"
    fi
else
    echo "  ⚠️  cloudflared未安装，仅支持本地/局域网访问"
    echo ""
    echo "  💡 如需外网访问，请运行："
    echo "     brew install cloudflared"
fi

echo ""
echo "  ⏹️  停止服务方法："
echo "     1. 关闭此终端窗口"
echo "     2. 或按 Ctrl+C"
echo ""
echo "=========================================="

# 保持脚本运行，按Ctrl+C时清理进程
trap "echo ''; echo '🛑 正在停止服务...'; kill $FLASK_PID 2>/dev/null; kill $TUNNEL_PID 2>/dev/null; exit 0" INT

# 显示实时日志
sleep 1
echo "  📊 服务日志（按Ctrl+C停止）："
echo ""
tail -f /tmp/flask_app.log /tmp/cloudflared.log 2>/dev/null

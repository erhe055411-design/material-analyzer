cd /Users/test/Desktop/巨量ai工作引擎/material-analyzer && lsof -t -i :8080 | xargs kill -9 2>/dev/null; sleep 1; nohup python3 app.py > /tmp/flask.log 2>&1 & sleep 2; echo "服务已重启"; tail -8 /tmp/flask.log

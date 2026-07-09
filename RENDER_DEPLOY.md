# Render 免费部署指南

目标：把当前 Flask 素材经营分析系统部署为可在线访问的网址。

## 1. 上传到 GitHub

把 `material-analyzer` 项目上传到一个 GitHub 仓库。

注意不要上传 `.env` 文件，API Key 只放 Render 环境变量。

## 2. 在 Render 创建服务

1. 打开 https://render.com
2. 注册/登录
3. New + → Web Service
4. 连接 GitHub 仓库
5. 选择本项目仓库

如果仓库根目录就是 `material-analyzer`，按默认即可。
如果仓库里还有上级目录，Root Directory 填：

```text
material-analyzer
```

## 3. Render 配置

Build Command：

```bash
pip install -r requirements.txt
```

Start Command：

```bash
gunicorn app:app --bind 0.0.0.0:$PORT
```

Plan 选择 Free。

## 4. 环境变量

在 Render 的 Environment 里添加：

```text
AI_API_KEY=你的DeepSeekKey
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
AI_TIMEOUT=30
```

不要把 API Key 写进前端代码，也不要提交到 GitHub。

## 5. 部署后访问

部署成功后，Render 会给你一个网址，例如：

```text
https://material-analyzer.onrender.com
```

别人打开这个网址即可使用。

## 免费版限制

- 免费实例长时间无人访问会休眠，首次打开可能较慢。
- 当前使用 SQLite，本地文件存储不适合作为正式长期数据库。
- 重新部署或平台回收实例时，上传数据可能丢失。
- AI 调用仍会消耗你的 DeepSeek API 余额。

如果要长期正式使用，建议后续升级 PostgreSQL 数据库和对象存储。

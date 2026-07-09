# AI 能力接入与 Serverless 部署说明

## 是否需要后端？

需要。浏览器前端不能直接调用大模型服务商接口，因为 API Key 会暴露在 JS、Network 请求或源码中。正确链路是：

```text
网页前端
  ↓ 只提交素材ID/用户问题
后端或 Serverless Function
  ↓ 从环境变量读取 AI_API_KEY
大模型服务商 OpenAI-compatible API
  ↓
后端/Serverless 清洗结果
  ↓
网页前端展示
```

## 本项目当前实现

当前项目是 Flask 后端，已按“Serverless 代理”思路实现为无状态 AI 调用：

- `POST /api/projects/<pid>/ai-diagnosis`
  - AI 智能诊断
  - 配置了 `AI_API_KEY` 时调用大模型
  - 未配置或调用失败时自动降级为本地规则诊断

- `POST /api/projects/<pid>/ai-chat`
  - AI 深度分析/问答
  - 必须配置 `AI_API_KEY`

API Key 只从环境变量读取，不写入前端代码。

## 环境变量

通用配置：

```bash
AI_API_KEY=你的APIKey
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
AI_TIMEOUT=30
```

也兼容：

```bash
OPENAI_API_KEY=你的APIKey
DEEPSEEK_API_KEY=你的APIKey
```

优先级：`AI_API_KEY` > `OPENAI_API_KEY` > `DEEPSEEK_API_KEY`。

## 常见模型供应商配置

### DeepSeek

```bash
AI_API_KEY=你的DeepSeekKey
AI_BASE_URL=https://api.deepseek.com/v1
AI_MODEL=deepseek-chat
```

### 通义千问 DashScope 兼容模式

```bash
AI_API_KEY=你的DashScopeKey
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_MODEL=qwen-plus
```

### OpenAI

```bash
AI_API_KEY=你的OpenAIKey
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
```

## 最简单 Serverless 方案

如果未来把前端部署成静态网页，建议把两个 Flask 路由拆成 Serverless Function：

```text
/api/ai-diagnosis
/api/ai-chat
```

Serverless Function 内部复用当前 `call_ai_chat()` 的逻辑：

1. 接收前端请求
2. 校验项目/素材参数
3. 从平台环境变量读取 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL`
4. 请求 `/chat/completions`
5. 返回 JSON 给前端

可选平台：Vercel Functions、Netlify Functions、Cloudflare Workers、阿里云函数计算、腾讯云 SCF。国内模型建议优先选能稳定访问对应 AI 服务商的云函数区域。

## 安全要求

- 不要把 API Key 写进 `static/js/app.js`
- 不要把 API Key 提交到 Git
- 本地 `.env` 也不要提交
- 生产环境在平台控制台配置环境变量
- 前端只请求自己的后端/Serverless 接口

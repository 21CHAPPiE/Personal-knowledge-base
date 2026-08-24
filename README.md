# Personal Knowledge Base（个人知识库）

面向个人项目与日常知识持续积累的云端个人知识库 MVP。

- **手机**（浏览器/PWA）：随时录入文本、上传截图、录制并上传语音
- **PC**（浏览器）：浏览、全文搜索、管理项目与知识、查看项目上下文
- **Coding Agent**（Claude Code / Codex）：通过 MCP 搜索知识、写入知识、获取/追加项目上下文
- **LLM 增强（可选）**：配置 Qwen（OpenAI-compatible API）后可生成摘要、推荐 tags；不配置时系统完全可用

技术栈：Python 3.9 + FastAPI + SQLite(FTS5) + 附件目录 / Vue 3 + TypeScript + Vite(PWA) / 零依赖 MCP server。
架构细节见 [docs/architecture.md](docs/architecture.md)，API 文档见 [docs/api.md](docs/api.md)，后续开发指引见 [CLAUDE.md](CLAUDE.md)。

## 快速开始（新机器）

要求：Python 3.9+、Node 18+。

```bash
# 1. 后端
cd backend
pip install -r requirements.txt
# 可选：复制 .env.example 为 .env 并填入 QWEN_* 等配置
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 健康检查：curl http://127.0.0.1:8000/health

# 2. 前端（另一个终端）
cd frontend
npm install
npm run dev
# 打开 http://127.0.0.1:5173 （开发模式自动代理 /api 与 /uploads 到 8000）
# 生产构建：npm run build，产物在 frontend/dist
```

Windows 下也可用 `scripts/dev.ps1` 一键启动前后端，Linux/macOS 用 `scripts/dev.sh`。

数据落在 `data/`（`knowledge.db` + `uploads/`），不进入 Git。

## MCP 接入（Claude Code）

先确保 backend 已启动（默认 http://127.0.0.1:8000）。

```bash
claude mcp add kb -- python path/to/mcp/kb_mcp_server.py
```

或写入 `~/.claude.json` / 项目 `.mcp.json`：

```json
{
  "mcpServers": {
    "kb": {
      "command": "python",
      "args": ["D:/aaa_hydro/Personal-knowledge-base/mcp/kb_mcp_server.py"]
    }
  }
}
```

提供工具：`kb_search`、`kb_get`、`kb_add`、`kb_recent`、`project_get_context`、`project_append_context`。
`KB_BASE_URL` 环境变量可指定 backend 地址。

## 测试

```bash
cd backend
python -m pytest tests -q
```

端到端验证（backend 需已启动）：

```bash
python scripts/e2e_verify.py
```

## 目录结构

见 [CLAUDE.md](CLAUDE.md)。

## 边界（第一版刻意不做的事）

不引入 Kubernetes / Redis / Celery / Kafka / Elasticsearch / 独立向量库 / 微服务 / RBAC / ORM；
单用户、无认证后端、SQLite 单文件、数据可整体迁移（拷贝 data/ 目录）。

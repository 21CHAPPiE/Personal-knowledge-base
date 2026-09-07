# Personal Knowledge Base（个人知识库）

面向个人项目与日常知识持续积累的云端个人知识库 MVP。

- **手机**（浏览器/PWA）：随时录入文本、上传截图、录制并上传语音
- **PC**（浏览器）：浏览、全文搜索、管理项目与知识、查看项目上下文
- **Coding Agent**（Claude Code / Codex）：通过 MCP，或本仓库自带的 `kb` Skill（项目内自动发现，无需注册），搜索知识、写入知识、获取/追加项目上下文
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
`KB_BASE_URL` 环境变量可指定 backend 地址；backend 配了 `KB_API_TOKEN` 的话，MCP server 也要配同一个
`KB_API_TOKEN` 环境变量，否则请求会被 401 拒绝。

## Skill 接入（Claude Code，项目内自动发现，无需注册）

仓库自带一个项目级 Skill：[`skills/kb/SKILL.md`](skills/kb/SKILL.md)。只要 Claude Code 在
**这个项目目录下**启动新会话，就会自动发现名为 `kb` 的 skill，不需要像 MCP 那样手动
`claude mcp add` 注册——效果一样，都是直接调 REST API。

注意：skill 是在会话启动时扫描的，**已经打开的旧会话看不到新加的 skill，需要开一个新会话**才会出现在可用列表里。

首次使用时它会在对话里问你 `KB_BASE_URL` 和 `KB_API_TOKEN`（后端没配置鉴权可以留空），
答案会存到 `~/.claude/kb-credentials`（用户主目录下，**不在仓库里**——这个仓库是 public 的，
任何密钥都不能提交进来），下次就不会再问。

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
单用户、SQLite 单文件、数据可整体迁移（拷贝 data/ 目录）。认证是可选的共享密钥（`KB_API_TOKEN`），
不是多用户账号系统——公网暴露前建议配置，纯本地用不配也行。

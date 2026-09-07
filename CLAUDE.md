# CLAUDE.md — 个人知识库（Personal Knowledge Base）

给后续 agent 会话的项目指引。先读本文件，再按需读 `docs/architecture.md`（架构与数据流）和 `docs/api.md`（完整 API 参考）。

## 项目目标

面向个人项目与日常知识持续积累的个人知识库 MVP，三类消费者：

1. **手机浏览器 / PWA**：随时录入文本、上传截图、录制并上传语音
2. **PC 浏览器**：浏览、全文搜索、管理项目与知识、查看项目上下文
3. **Coding Agent（Claude Code / Codex）**：通过 MCP 搜索知识、写入知识、获取/追加项目上下文

核心原则：**每条知识属于「日常知识」或某个具体 Project**；Qwen LLM 是可选增强（摘要 + tag 建议），不配置时系统完全可用；STT 是 adapter，未配置时语音正文留空不虚构；OCR/VLM 只留接口不假装。

## 架构

- **Backend**：Python 3.9 + FastAPI + SQLite（WAL，FTS5 全文搜索）。单进程单库，无 ORM、无 Redis、无 Celery。
- **Frontend**：Vue 3 + TypeScript + Vite，PWA（静态 manifest + 手写 service worker）。开发模式由 Vite 代理 `/api`、`/uploads`、`/health` 到 127.0.0.1:8000。
- **MCP**：`mcp/kb_mcp_server.py`，零第三方依赖的 stdio JSON-RPC 2.0（newline-delimited）server。只调 REST，不直连数据库（单一事实源）。
- **LLM/STT**：Provider 抽象（`backend/app/providers/`），env 驱动工厂，未配置时 Noop 降级（诚实的截断摘要 / 空 tags / None transcript），绝不伪装。
- 详细数据流（手机录入、MCP、provider 选择）见 `docs/architecture.md`。

## 目录说明

```
backend/            FastAPI 应用
  app/api/          路由（projects/knowledge/attachments/search/llm/stats）
  app/db/           schema.sql + 连接/初始化（FTS5 external-content + 同步触发器）
  app/models/       pydantic schemas
  app/providers/    LLM/STT 抽象 + Qwen 实现 + Noop 降级 + 工厂
  app/services/     业务逻辑（project/knowledge/attachment/search/context/stats）
  tests/            pytest（每测试独立临时库；basetemp 固定在 backend/.testtmp/）
frontend/           Vue 3 + TS + Vite PWA（views: Dashboard/知识列表/详情/新建/项目/搜索）
mcp/                kb_mcp_server.py（零依赖 MCP stdio server）
scripts/            dev.ps1 / dev.sh（一键起前后端）、e2e_verify.py（需 backend 已启动）
docs/               architecture.md、api.md
data/               knowledge.db + uploads/（.gitignore，整体拷贝即迁移）
```

## 核心数据模型

- **Project**：id, name(UNIQUE, 忽略大小写), description, status(active/archived/done), created_at, updated_at
- **KnowledgeItem**：id, project_id(可空=日常知识), type(text/voice/screenshot/project_note), title, content, source, tags(逗号串), summary, created_at, updated_at
- **Attachment**：id, knowledge_id, filename(原始名), mime_type(魔数识别), size_bytes, stored_name(uuid 前缀+扩展名), created_at
- FTS5 外部内容表 `knowledge_fts`（title/content/tags），AFTER INSERT/UPDATE/DELETE 触发器保持同步；查询按 bm25(title 5.0, content 1.0, tags 2.0) 排序，中文短词（2 字）走 LIKE 回退合并——unicode61 与 trigram 对 2 字中文都不可靠，这是实测结论。
- 时间：UTC `YYYY-MM-DDTHH:MM:SSZ` 字符串。

## 开发命令

```bash
# 后端（Python 3.9，anaconda 环境）
cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 前端
cd frontend && npm install && npm run dev   # http://127.0.0.1:5173
# 一键（任选其一）
scripts/dev.ps1   # Windows
scripts/dev.sh    # Linux/macOS
```

## 测试命令

```bash
cd backend && python -m pytest tests -q        # 后端全量（当前 58 项）
python scripts/e2e_verify.py                   # 真实 HTTP 端到端（backend 必须先启动）
cd frontend && npm run typecheck && npm run build
```

注意：Windows 下 pytest 默认 basetemp（%TEMP%\pytest-of-*）易被锁，conftest 已把 basetemp 固定到 `backend/.testtmp/`，直接跑 `python -m pytest tests -q` 即可。

## 环境变量

见 `.env.example`（backend 启动前 export 或写入环境即可，不读 .env 文件）：

- `KB_DATA_DIR`（默认 `data/`）、`KB_UPLOAD_MAX_BYTES`（默认 10485760）、`KB_HOST`/`KB_PORT`
- `QWEN_BASE_URL` / `QWEN_API_KEY` / `QWEN_MODEL`（OpenAI-compatible `/v1/chat/completions` 前缀）
- `STT_BASE_URL` / `STT_API_KEY` / `STT_MODEL`（`/audio/transcriptions`）
- `KB_BASE_URL`（仅 MCP server 用，默认 http://127.0.0.1:8000）
- `KB_API_TOKEN`（可选，共享密钥鉴权，未配置时不校验；配置后除 `/health` 外所有请求含 `/uploads/*` 都要带 `Authorization: Bearer <token>`；给公网暴露前的最低限度保护，不是多用户账号系统。backend 配了这个后，MCP server 也要配同一个值，否则 MCP 调用会 401）

配置在**每次调用时读取**（Settings 工厂，无模块级单例），测试可直接 monkeypatch 环境变量。

## 编码规范

- Python 3.9：用 `Optional[X]`/`List[X]`，不用 `X | Y`；不用 match
- 每个请求一个 sqlite 连接（FastAPI 依赖注入），`PRAGMA foreign_keys=ON`，WAL
- 服务层返回 dict 由 API 层序列化；内部组合查询用 `*_rows`（原始 Row）避免双重序列化
- 附件：uuid4().hex[:12]+扩展名存储名、扩展名白名单、魔数识别 MIME、`resolve()`+前缀检查防穿越
- 前端：TypeScript 严格模式必须过（`npm run typecheck`）；API 封装在 `frontend/src/api/client.ts`
- 中文文件一律 UTF-8；Windows 控制台注意（MCP server 已强制 stdio UTF-8）
- FTS 查询词逐词双引号转义（`""` 转义），防止 `AND`/`OR`/`NEAR` 劫持语义

## 禁止事项

- 不引：Kubernetes / Redis / Celery / Kafka / Elasticsearch / 独立向量库 / 微服务 / RBAC / ORM（SQLAlchemy 等）/ 官方 `mcp` 包（要求 Python 3.10+，我们在 3.9）
- 不让 LLM 成为硬依赖：任何 LLM 路径必须有 Noop/fallback
- 不在仓库里放：API key、`data/`、`node_modules/`、`venv/`、`frontend/dist/`、`backend/.testtmp/`、`*.log`
- 不让 MCP 直连 DB：一切走 REST
- 不在 POST /api/knowledge 用 JSON body：它是 multipart（要支持文件），JSON 会 422
- 不删 `data/uploads/.gitkeep` 和 `data/.gitkeep`

## MCP 使用方式

```bash
claude mcp add kb -- python D:/aaa_hydro/Personal-knowledge-base/mcp/kb_mcp_server.py
# 或 .mcp.json: {"mcpServers":{"kb":{"command":"python","args":["<path>/mcp/kb_mcp_server.py"]}}}
```

工具：`kb_search(query, project_id?, type?, limit?)`、`kb_get(id)`、`kb_add(title, content, type?, project_id?, tags?, source?)`、`kb_recent(limit?)`、`project_get_context(project)`、`project_append_context(project, content, title?)`。
`project` 参数可为项目名或数字 id。backend 必须先启动。

## 当前已完成（2026-08-24）

- 后端全部 API：项目 CRUD、知识 CRUD（含 multipart 附件）、FTS5+LIKE 中文搜索、项目上下文/追加、LLM 摘要/tag 建议（含 fallback 与 502 语义）、stats、health
- 前端 PWA：Dashboard、知识列表/详情/新建（文本/截图/语音三模式）、项目列表/详情（含上下文视图与时间线）、搜索；`vue-tsc` 与 `vite build` 通过
- MCP：6 工具，零依赖 stdio；真实子进程往返验证通过（含中文+tags、按名/按 id 解析项目）
- 测试：58 项后端 pytest 全过；`scripts/e2e_verify.py` 13 项真实 HTTP 检查全过
- 集成验证（真实启动）：/health、项目创建、知识写入、附件字节往返、中英文搜索、项目上下文、前端页面/代理/PWA 资源/SPA 路由均实测通过

## 当前待办

- [ ] 真实移动端走查：手机浏览器实际录一条语音 + 拍一张图（桌面已验证接口与页面）
- [ ] 配置真实 Qwen key 后验证 summarize/suggest-tags 真路径（当前验证了 fallback 与错误路径）
- [ ] 生产部署形态：`npm run build` 产物由 backend StaticFiles 托管（或反向代理）的脚本
- [ ] 语音/截图的 OCR/VLM 理解（接口已预留：providers 抽象 + 摘要字段）
- [ ] 数据备份/导出（当前：整体拷贝 data/ 目录）
- [ ] 删除验证数据：`data/` 里留有 e2e/MCP 验证产生的条目（E2E 集成项目等），介意的话删库重建即可

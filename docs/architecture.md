# 架构文档 — 个人知识库 (Personal Knowledge Base)

本文档定义系统边界、数据模型、API、以及关键数据流。它是实现与后续维护的依据。

## 1. 系统边界

本系统是**单用户个人知识库 MVP**，不是企业级平台。第一版组件只有四个：

| 组件 | 技术 | 说明 |
|------|------|------|
| Backend | Python 3.9 + FastAPI | 唯一后端，提供 REST API；/health 健康检查 |
| Frontend | Vue 3 + TypeScript + Vite (PWA) | PC/手机浏览器使用；静态资源由 vite dev 提供，构建产物可被任意静态服务器托管 |
| 数据库 | SQLite（单文件 data/knowledge.db，WAL 模式） | FTS5 全文索引（unicode61 + LIKE 回退，见 §6） |
| 附件目录 | data/uploads/ | 原图/音频等二进制，服务端生成安全文件名 |
| MCP Server | mcp/kb_mcp_server.py（零第三方依赖，Python stdio JSON-RPC） | 供 Claude Code / Codex 读写知识库 |
| LLM 接入 | Qwen（OpenAI-compatible API），Provider 抽象 | 未配置时系统完全可用，见 §7 |

明确**不引入**（除非代码现状依赖）：Kubernetes、Redis、Celery、Kafka、Elasticsearch、独立向量数据库、微服务、RBAC、消息队列、ORM（直接用 sqlite3）。

部署形态（第一版）：单机 `backend` 监听 8000，`frontend` 开发时 5173 并代理 /api 与 /uploads 到 backend；生产构建后由 backend 静态托管或任意静态服务器托管，二者同源或经 CORS 配置。手机通过局域网/内网穿透访问同一后端。

## 2. 数据模型

```
projects            knowledge_items                attachments
  id PK               id PK                          id PK
  name UNIQUE         project_id FK -> projects.id    knowledge_id FK -> knowledge_items.id (CASCADE)
  description         type (text|voice|screenshot|   filename        原始文件名（元数据）
  status              project_note)                  stored_name     服务端安全文件名
  created_at          title                          mime_type
  updated_at          content                        file_path       相对 uploads 的路径
                      source                         size_bytes
                      tags (逗号分隔)                created_at
                      summary (LLM 生成，可空)
                      created_at
                      updated_at

knowledge_fts (FTS5 external-content 表，映射 knowledge_items)
  通过 AFTER INSERT/UPDATE/DELETE 触发器与主表同步
```

设计取舍：

- **tags 用逗号分隔字段**而非关联表：个人规模下足够，避免过度范式化；检索时 LIKE + 前后逗号匹配。
- **updated_at** 由服务端统一维护，任何 UPDATE 都会刷新。
- 时间戳统一存 UTC ISO-8601（`YYYY-MM-DDTHH:MM:SSZ`）。"今日新增"按服务端本地日期计算（单用户场景服务端即本机）。
- 知识 `source` 记录来源（manual / web / agent / voice / screenshot…），用于审计与过滤。
- `project_note` 类型 + `project_append_context` 端点构成项目时间线：MCP/前端追加的进展都是普通知识条目，天然获得全文索引与历史。

## 3. REST API（前缀 /api，另 /health 与 /uploads/*）

### 3.1 总览

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | /health | 健康检查（含 db 可读、uploads 可写） |
| GET | /api/stats | Dashboard 数据：今日新增、累计、最近知识、最近更新项目 |
| GET | /api/projects | 列表（可选 status 过滤） |
| POST | /api/projects | 创建 {name, description?, status?} |
| GET | /api/projects/{id} | 详情 |
| PATCH | /api/projects/{id} | 更新 name/description/status |
| DELETE | /api/projects/{id} | 删除（知识条目 project_id 置空） |
| GET | /api/projects/{id}/context | 项目上下文：简介+统计+时间线+最近条目 |
| POST | /api/projects/{id}/context/append | 追加项目进展（type=project_note, source=agent） |
| GET | /api/knowledge | 列表（project_id/type/tag/q 过滤 + limit/offset） |
| POST | /api/knowledge | 创建（JSON 或 multipart，可带 file 字段直接附附件） |
| GET | /api/knowledge/recent | 最近知识（limit），先于 /{id} 注册 |
| GET | /api/knowledge/{id} | 详情（含附件） |
| PATCH | /api/knowledge/{id} | 更新 title/content/tags/project_id/type/summary |
| DELETE | /api/knowledge/{id} | 删除（附件级联删文件+行） |
| GET | /api/knowledge/{id}/attachments | 附件列表 |
| POST | /api/knowledge/{id}/attachments | 上传附件（multipart file，≤10MB） |
| GET | /api/attachments/{id} | 下载/内联访问附件 |
| DELETE | /api/attachments/{id} | 删附件 |
| GET | /api/search?q=&project_id=&type=&limit= | 全文搜索（§6） |
| GET | /api/llm/status | LLM/STT Provider 配置状态 |
| POST | /api/llm/summarize | 对单条知识生成摘要（未配置时回退截断） |
| POST | /api/llm/suggest-tags | 推荐 tags（未配置时回退空列表） |

### 3.2 统一约定

- 错误：HTTP 状态码 + `{"detail": "..."}`。400 参数错误、404 缺失记录、409 名称冲突、413 文件过大、415 类型不符。
- 写操作返回更新后的完整实体。
- 所有列表端点支持 `limit`（默认 20，最大 100）与 `offset`。

## 4. 目录结构

```
Personal-knowledge-base/
├── backend/
│   ├── app/
│   │   ├── main.py            # create_app、路由注册、启动初始化
│   │   ├── config.py          # 环境变量读取（KB_DATA_DIR、QWEN_* 等）
│   │   ├── api/               # FastAPI 路由（projects/knowledge/search/llm/stats）
│   │   ├── models/            # pydantic schema
│   │   ├── services/          # 业务逻辑（project/knowledge/attachment/search/context/stats）
│   │   ├── providers/         # LLM/STT 抽象与 Qwen 实现、工厂
│   │   └── db/                # schema.sql、连接管理、初始化
│   ├── tests/                 # pytest（httpx ASGI 直连，无外部依赖）
│   └── requirements.txt
├── frontend/                  # Vue3+TS+Vite PWA（views: Dashboard/Knowledge*/Projects/ProjectDetail/Search）
├── mcp/kb_mcp_server.py       # 零依赖 MCP stdio server，调用 backend REST
├── data/                      # knowledge.db + uploads/（.gitignore 管理，.gitkeep 保留目录）
├── scripts/                   # dev.ps1 / dev.sh
├── docs/                      # architecture.md / api.md
├── .env.example
├── .gitignore
├── CLAUDE.md
└── README.md
```

## 5. 手机录入数据流

1. **文本**：PWA 快速录入页（标题/正文/Project/Tag）→ `POST /api/knowledge` → 入库并同步 FTS。
2. **截图**：`<input type=file accept="image/*" capture>` 或相册选择 → multipart 上传（file 字段与标题/正文同一次请求）→ 服务端校验（≤10MB、扩展名白名单、mime 嗅探）→ 存 `data/uploads/<uuid8>_<safeext>`，写 attachments 行，知识 type=screenshot。
3. **语音**：MediaRecorder 录制 → 得到 webm/ogg blob → multipart 上传 → type=voice，原音频保存；若 STT Provider 已配置则调用转写并写入 content，未配置则 content 留空/占位说明，**不虚构转写**。
4. 原图/原始音频永远保留；LLM/OCR/VLM 结果只写 summary/content 字段，可重新生成。

## 6. 搜索数据流与策略

- 主引擎：SQLite FTS5（external-content 表 + 触发器同步），unicode61 分词，bm25 排序，支持标题/正文/tags 字段加权，支持 project_id、type、tag 过滤。
- CJK 回退：unicode61 对中文按连续字符整词分词，2 字中文词（如"数据"）FTS 无法命中。对每个查询词追加 `title LIKE / content LIKE` 子串匹配（个人数据量下成本可接受），与 FTS 结果去重合并，FTS 命中优先排序。
- 查询词转义：FTS 查询中每个词加双引号包裹并转义内部引号，防止 `AND/OR/NEAR` 被用户输入劫持；空词、纯标点词降级为 LIKE-only。
- 这是"无向量数据库的语义近似"：不做 embedding，避免为语义搜索强加独立向量库（产品边界要求）。

## 7. Qwen Provider 数据流

```
env: QWEN_BASE_URL / QWEN_API_KEY / QWEN_MODEL   （.env 或系统环境，禁止入库）
providers/base.py:  LLMProvider(summarize, suggest_tags) / STTProvider(transcribe) 抽象
providers/qwen.py:  OpenAI-compatible POST {base}/chat/completions，httpx 调用
providers/factory.py: 按 env 构造；未配置 → Noop 实现（摘要=截断正文，tags=[]，STT=None）
```

- API Key 只存在于 backend 进程环境，前端只调 `/api/llm/*`，不接触 Key。
- LLM 失败（网络/超时/非 200）→ 返回 502 或按端点语义回退 Noop 结果，**不阻塞**知识增删改查主流程。
- 图片理解/OCR：第一版只预留 `analyze_image` 接口位置，未配置时明确返回 "raw-only"，不伪装已实现 VLM。

## 8. MCP 数据流

```
Claude Code / Codex
   └─(stdio JSON-RPC)→ mcp/kb_mcp_server.py（零依赖 Python）
        └─(HTTP, KB_BASE_URL, 默认 http://127.0.0.1:8000)→ backend REST
```

工具：`kb_search(query, project_id?, type?, limit?)`、`kb_get(id)`、`kb_add(title, content, type?, project_id?, tags?, source?)`、`kb_recent(limit?)`、`project_get_context(project)`（project 为名称或 id，返回渲染后的文本上下文）、`project_append_context(project, content, title?)`。

协议：stdio 换行分隔 JSON-RPC 2.0；实现 initialize / notifications/initialized / tools/list / tools/call / ping；日志只写 stderr；对未知方法返回 -32601。MCP server 不直连数据库——一切经 REST，保证单一事实来源。

## 9. 安全与工程约束

- 附件路径：`stored_name = uuid4().hex[:12] + '_' + safe_ext`；落盘前 `os.path.normpath` 并校验仍在 uploads 根内，防路径遍历。
- 上传限制：默认 10MB/文件；原始文件名只做元数据展示（清洗控制字符），服务端文件名才是存储依据。
- SQLite：WAL（并发读）、`foreign_keys=ON`、每请求独立连接、`row_factory=Row`。
- 跨平台路径全部 `pathlib`/`os.path`，不硬编码分隔符；UTF-8 显式编码（含 Windows 控制台输出）。
- 密钥只进 `.env`（`.env` 进 .gitignore）；`.env.example` 给模板。

## 10. 测试策略

- Backend：pytest + FastAPI TestClient（httpx ASGI），覆盖 project CRUD、knowledge CRUD、search（FTS+LIKE 回退）、attachment（大小/扩展名/路径遍历）、project 关联、malformed request、missing record、LLM 未配置回退、MCP 工具与 REST 的映射。
- Frontend：`npm run build` 通过（vue-tsc 类型检查 + 产物生成）；核心交互在 STEP 8 手工/E2E 验证。
- MCP：对运行中的 backend 做真实 round-trip（tools/list + tools/call 六工具）。
- E2E：scripts/e2e_verify.py 串起 health→建项目→写知识→搜索→传附件→取上下文→MCP 调用，输出逐项 PASS/FAIL。

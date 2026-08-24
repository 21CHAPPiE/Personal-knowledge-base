# REST API 参考

后端基础地址默认 `http://127.0.0.1:8000`。除特别说明外，请求/响应均为 JSON（UTF-8）。
时间格式统一为 UTC `YYYY-MM-DDTHH:MM:SSZ`。

## 系统

- `GET /health` → `{"status":"ok","db":"ok","uploads":"ok","llm":"<provider>","stt":"<provider>"}`
  检查数据库可读、uploads 目录可写、当前 LLM/STT provider 名称（未配置时为 `noop`）。

## 项目 `/api/projects`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/projects?status=` | 项目列表（status 可选过滤：active/archived/done） |
| POST | `/api/projects` | 创建。body：`{"name": "…", "description": "…"}`；重名（忽略大小写）返回 409 |
| GET | `/api/projects/{id}` | 单个项目；404 若不存在 |
| PATCH | `/api/projects/{id}` | 更新。body 可含 `name` / `description` / `status` |
| DELETE | `/api/projects/{id}` | 删除项目；其下知识保留但 `project_id` 置空 |
| GET | `/api/projects/{id}/context` | 项目上下文：`{project, statistics, by_type, timeline(近30天), recent_items}` |
| POST | `/api/projects/{id}/context/append` | 追加进展（存为 `project_note`）。body：`{"content":"…","title":"…","source":"agent"}` → 201 返回新知识条目 |

## 知识 `/api/knowledge`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/knowledge?project_id=&type=&tag=&q=&limit=&offset=` | 列表；`q` 存在时走搜索（同 `/api/search` 语义） |
| GET | `/api/knowledge/recent?limit=` | 最近创建（默认 20，上限 100） |
| POST | `/api/knowledge` | **multipart/form-data** 创建。字段：`title`(1-200, 必填)、`content`(≤50000)、`type`(text/voice/screenshot/project_note, 默认 text)、`project_id`、`tags`(可重复)、`source`、`file`(可选附件)。201 返回完整条目含 attachments |
| GET | `/api/knowledge/{id}` | 单条（含 attachments）；404 若不存在 |
| PATCH | `/api/knowledge/{id}` | JSON 更新：`title`/`content`/`type`/`project_id`/`tags`/`source`/`summary` 任意子集 |
| DELETE | `/api/knowledge/{id}` | 删除条目及其附件 |
| GET | `/api/knowledge/{id}/attachments` | 条目附件列表 |
| POST | `/api/knowledge/{id}/attachments` | multipart 追加附件（字段 `file`）；扩展名白名单 + 魔数 MIME 识别 + 大小上限（`KB_UPLOAD_MAX_BYTES`，默认 10MB，超限 413） |

## 附件

- `GET /api/attachments/{id}` → 附件元数据（含 `url`，形如 `/uploads/<stored_name>`）
- `DELETE /api/attachments/{id}`
- `GET /uploads/<stored_name>` → 原始字节（StaticFiles，路径穿越防护）

## 搜索 `/api/search`

- `GET /api/search?q=…&project_id=&type=&limit=&offset=`（`q` 必填，1-200 字符）
- FTS5（bm25 排序，title 权重 5.0 / tags 2.0 / content 1.0）+ 中文短词 LIKE 回退合并去重；
  查询词经转义，`AND`/`OR`/`NEAR`/括号不会改变语义。

## LLM `/api/llm`

- `GET /api/llm/status` → LLM/STT 配置状态
- `POST /api/llm/summarize` → body `{"knowledge_id": 1, "fallback": true}`；
  成功返回 `{summary, provider, ...}`；provider 报错且 `fallback=true` 时用无 LLM 摘要降级（`provider: "fallback"`）；`fallback=false` 报错时 502
- `POST /api/llm/suggest-tags` → body `{"knowledge_id": 1, "apply": false, "fallback": true}`；
  `apply=true` 时把推荐 tags 合并写回条目

## 统计

- `GET /api/stats` → `{today_count, total_items, total_projects, recent_items(10), updated_projects(5)}`；
  `today_count` 以本机时区零点为界

## 错误约定

- 404：项目/条目/附件不存在（`detail` 为字符串）
- 409：项目重名
- 413：附件超限（`KB_UPLOAD_MAX_BYTES`）
- 422：FastAPI 参数校验（`detail` 为校验错误数组）
- 502：LLM provider 失败且 `fallback=false`

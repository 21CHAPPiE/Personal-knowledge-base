# 教训系统（Lessons）实施计划

给实施者的施工文档。目标是让 agent **不要在同一类问题上重复踩坑**。

阅读顺序：先读本文件全文，再读 `CLAUDE.md`、`docs/api.md`、`skills/kb/SKILL.md`。
**不确定的地方停下来问，不要猜着改。**

---

## 0. 这套系统要解决什么

闭环有四环，缺一环整套失效：

1. **捕获** —— 踩坑当时把教训写下来
2. **寻址** —— 下次凭"当前遇到的状况"能找回来
3. **触发** —— 真的有机制在**动手之前**去查
4. **纠错** —— 教训过时了能改掉

本期只做 1、2、3 的最小可用闭环，4 放到后续计划。

核心设计判断：**瓶颈不在存储结构，在检索摩擦**。所以本期最重要的产出是那一个
`/api/lessons/match` 端点——它把"查一下以前踩没踩过"从"自己拼查询"降级成一次调用。

---

## 1. 硬性约束（违反任何一条 = 返工）

| 禁止 | 原因 |
|---|---|
| ❌ 不许改 `backend/app/db/schema.sql` 的任何表结构 | `type` 列有 `CHECK (type IN ('text','voice','screenshot','project_note'))`，且建表语句是 `CREATE TABLE IF NOT EXISTS`——线上库已存在，改了 schema.sql **对已有库完全不生效**，而本项目**没有任何迁移机制**。硬改会导致代码与线上库不一致 |
| ❌ 不许新增 `type='lesson'` 这种取值 | 同上，会被 CHECK 约束直接拒绝写入 |
| ❌ 不许新建数据库表 | 同上，没有迁移机制 |
| ❌ tag 的值里不许出现英文逗号 `,` | tags 在库里是逗号拼接存储的（见 `app/utils.py: parse_tags`），值里含逗号会被静默拆成两个 tag。已经踩过一次 |
| ❌ 不许引入任何新的第三方依赖 | 见 `CLAUDE.md` 禁止事项 |
| ❌ 不许用 `X \| Y` 类型语法、不许用 `match` 语句 | 本项目跑 Python 3.9，只能用 `Optional[X]` / `List[X]` |
| ❌ 不许在仓库里写入任何密钥 | 本仓库是 GitHub public |

**教训存在哪**：仍然存进现有的 `knowledge_items` 表，`type` 用 `'project_note'`，
靠 **tag** 区分它是一条教训。这是本方案能"零迁移"的唯一原因。

---

## 2. 数据约定（先定死，代码按这个写）

### 2.1 必须的 tag

| tag | 必填 | 说明 |
|---|---|---|
| `kind:lesson` | ✅ | 标识这是一条教训。`match` 端点只在带此 tag 的条目里搜 |
| `scope:machine` / `scope:project` / `scope:stack` / `scope:universal` | ✅ 且只能有一个 | 作用域层级，决定这条教训能迁移到多远 |
| `machine:<hostname>/<uuid前6位>` | 选填 | 例：`machine:X99/a3f2c1`。**`scope:machine` 的教训必填** |
| `os:linux` / `os:windows` / `os:macos` | 选填 | |
| `stack:<名字>` | 选填，可多个 | 例：`stack:vite`、`stack:fastapi`、`stack:python3.9` |
| `not:os:windows` 形式 | 选填，可多个 | **反作用域**：明确不适用于哪里 |

### 2.2 作用域层级怎么选（实施者要看懂，这是这套系统的价值所在）

放错层级两头都出事：**放太窄，换个项目白踩一遍；放太宽，错误迁移制造新 bug。**

| 层级 | 含义 | 真实例子 |
|---|---|---|
| `scope:machine` | 只对某台机器成立 | "这台机器设了 `all_proxy=socks5://127.0.0.1:10808`，localhost 的 curl 必须加 `--noproxy '*'`" |
| `scope:project` | 只对本仓库成立 | "`GET /api/knowledge` 的 limit 上限是 100" |
| `scope:stack` | 对用同一框架/语言的任何项目成立 | "Vite dev server 在反代/隧道后面要配 `server.allowedHosts`" |
| `scope:universal` | 到处都成立 | "浏览器在非 HTTPS 下拿不到麦克风（getUserMedia 需要安全上下文）" |

判断方法：问自己"换一台机器还成立吗？换一个项目还成立吗？换一个框架还成立吗？"
第一个"不成立"出现在哪一层，就选上一层。

**分支（git branch）**：可以记录在正文里，但**不要**做成 tag 参与匹配——绝大多数教训跟分支无关。

### 2.3 正文模板（严格按这个格式写，`match` 的匹配质量依赖它）

```
【触发签名】
<逐字复制的报错串 / 失败的命令 / 可观察症状，一行一条，可多行>

【根因】
<机制层面的原因，不是症状复述。只有根因能让教训泛化到同类问题>

【解法】
<实际有效的做法>

【不适用】
<明确不适用的场景；没有就写"暂无">

【验证】
<什么时候、以什么方式验证过>
```

**触发签名必须逐字**。因为本项目禁止向量库，检索只能靠 FTS5 关键词 + 子串匹配，
而报错原文是高区分度 token——概括成"网络有问题"这条教训就永远查不出来了。

---

## 3. 实施步骤

每一步做完都要跑验证命令，通过了再做下一步。

### Step 1：机器身份脚本

**新建** `scripts/machine_id.py`：

- 零第三方依赖，Python 3.9 兼容
- 读 `~/.claude/machine-id`；不存在则用 `uuid.uuid4().hex` 生成并写入（`chmod 600`）
- 打印一行：`<hostname>/<uuid前6位>`，例如 `X99/a3f2c1`
- 为什么不只用 hostname：hostname 会重名、会被改，uuid 才稳定唯一；两个都要，hostname 给人看

**验证**：
```bash
python3 scripts/machine_id.py   # 连跑两次，输出必须完全一致
```

### Step 2：后端 match 端点（本期核心）

**新建** `backend/app/services/lesson_service.py`，实现一个函数：

```python
def match_lessons(conn, signature: str, os_name: Optional[str] = None,
                  machine: Optional[str] = None, stack: Optional[List[str]] = None,
                  project_id: Optional[int] = None, limit: int = 10) -> List[dict]:
```

实现要点（**照抄 `app/services/search_service.py` 的写法风格**，它是最接近的参考）：

1. 只在带 `kind:lesson` tag 的条目里搜。tag 过滤用现有写法：
   `"(',' || k.tags || ',') LIKE ?"`，参数 `"%,kind:lesson,%"`
2. `signature` 用 **大小写不敏感的子串匹配**，匹配 `title` 或 `content`
   （`LIKE '%...%'`）。同时也跑一遍 FTS5，两路结果去重合并——直接参考
   `search_service.search()` 的双路合并逻辑
3. **打分**（在 Python 里算，不要写进 SQL）：
   - 基础分：signature 命中 = 5 分（没命中的条目不返回）
   - `machine` 传入且条目有匹配的 `machine:` tag → +3
   - `stack` 传入且条目有任一匹配的 `stack:` tag → +2
   - `project_id` 传入且条目 `project_id` 相同 → +2
   - 条目是 `scope:universal` → +1
4. **排除规则（必须实现，这是"不要错误迁移"的关键）**：
   - 条目有 `not:os:<x>` 且请求的 `os_name == x` → **直接排除**
   - 条目是 `scope:machine`，且请求传了 `machine` 但与条目的 `machine:` tag 不同
     → **直接排除**（机器级教训不跨机器）
   - 条目有 `os:<x>` 且请求的 `os_name` 不同 → **直接排除**
5. 按分数降序返回，同分按 `updated_at` 新的在前
6. 返回结构：复用 `app/services/common.py: knowledge_out()`，在每条上额外加
   `"match_score": <int>` 和 `"match_reasons": ["signature", "machine", ...]`

**新建** `backend/app/api/lessons.py`（照抄 `app/api/search.py` 的结构）：

```
GET /api/lessons/match
  signature: str  (必填, min_length=1, max_length=500)
  os: Optional[str]
  machine: Optional[str]
  stack: Optional[str]        # 逗号分隔多个，服务层用 parse_tags 拆
  project_id: Optional[int]
  limit: int = Query(10, ge=1, le=50)
```

**在** `backend/app/main.py` **里注册这个 router**（照现有 `app.include_router(...)` 的写法）。

**新建测试** `backend/tests/test_lessons.py`，至少覆盖：
- 写入 3 条带不同 scope tag 的教训，signature 命中的能查出来，不命中的查不出来
- `not:os:windows` 的条目，请求 `os=windows` 时被排除
- `scope:machine` 的条目，请求不同 machine 时被排除
- 打分排序正确（machine + stack 都命中的排在只命中 signature 的前面）
- 不带 `kind:lesson` tag 的普通知识条目**不会**出现在结果里

**验证**：
```bash
cd backend && python -m pytest tests -q
# 现有 67 项必须全过，加上新增的（新增数量以实际为准）
```

### Step 3：MCP 工具

**改** `mcp/kb_mcp_server.py`，新增两个工具（照抄现有 `tool_kb_search` 的写法）：

- `kb_lesson_match(signature, os?, machine?, stack?, project?, limit?)` → 调
  `GET /api/lessons/match`
- `kb_lesson_add(signature, root_cause, resolution, scope, machine?, os?, stack?, not_applicable?, project?)`
  → 按 §2.3 模板拼出正文，按 §2.1 拼出 tag 列表，调 `POST /api/knowledge`
  （**multipart，不是 JSON**）写入，`type=project_note`、`source=agent`

注意：现有 `_resolve_project()` 已经实现了"项目名或 id"的解析，直接复用。

**验证**：
```bash
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n' \
  | env http_proxy= https_proxy= all_proxy= python3 mcp/kb_mcp_server.py
# 应能看到 8 个工具（原 6 个 + 新增 2 个）
```

### Step 4：Skill 协议

**改** `skills/kb/SKILL.md`，加两节：

1. **动手前查**：在开始一类"以前踩过坑"的任务前（跑一个没跑过的命令、配一个新服务、
   搭一个新框架、动 systemd/网络/权限相关的东西），先调一次 `kb_lesson_match`，
   signature 用即将执行的命令或预期的错误关键字。
   **明确写清楚：不是每个动作都查**——只在上述高风险任务类别查，否则 token 开销大于收益。
2. **解决后写**：非平凡问题（花了超过一两轮才搞定的）解决后，按 §2.1/§2.3 写一条教训。
   写之前先 match 一次，如果已有等价教训就**更新那条**（`PATCH /api/knowledge/<id>`），
   不要写重复的。

### Step 5：文档同步

- `docs/api.md`：新增 `/api/lessons/match` 的说明（照现有格式）
- `README.md`：在 Skill 章节提一句这套教训机制
- `CLAUDE.md`：在环境变量/约定部分提一句 tag 规范

---

## 4. 验收标准

全部满足才算完成：

1. `cd backend && python -m pytest tests -q` 全绿，且新增测试覆盖了 §3 Step 2 列出的 5 个场景
2. `python3 scripts/machine_id.py` 连续两次输出一致
3. MCP `tools/list` 返回 8 个工具
4. 端到端手测（backend 需已启动，注意带 `Authorization: Bearer $KB_API_TOKEN`，
   且 curl 要加 `--noproxy '*'`）：
   - 用 `kb_lesson_add` 写一条 `scope:stack` + `stack:vite` 的教训
   - 用 `kb_lesson_match` 传该教训的 signature 片段，能查出来
   - 传一个完全无关的 signature，查不出来
5. 没有修改 `schema.sql`，`git diff` 里不包含该文件
6. 所有新增 tag 的值里都没有英文逗号

---

## 5. 后续完善计划（本期不做，按优先级排）

### P1 — 去重与置信度
同一条教训被多个会话重复写入是必然会发生的。做法：`kb_lesson_add` 写入前强制先
match，命中高相似度就改成更新已有条目，并在正文加一行 `【复现】<日期>`，
让"被验证过几次"变成可见信号。**这是最先该补的，因为不做的话库会被噪音淹没。**

### P2 — 教训失效与取代
教训会过时（依赖升级、配置变更）。加 `status:stale` / `superseded-by:<id>` tag，
`match` 端点默认过滤掉 stale 的。需要一个"发现教训不对时怎么标记"的协议写进 Skill。

### P3 — 把高频教训提升进 `CLAUDE.md`
KB 检索始终需要主动调用，而 `CLAUDE.md` 是每次会话自动进上下文的。定期（或当某条
教训的复现次数超过阈值时）把最要命的几条**同时**写进 `CLAUDE.md`——零检索成本。
这是对本方案的补充，不是替代。

### P4 — 前端教训视图
在知识图谱页面把 `kind:lesson` 的节点用不同颜色标出来，并支持按 scope 层级筛选；
或者单独做一个教训列表页，支持按 machine/stack/os 筛。

### P5 — 跨机器教训同步的真实验证
目前所有教训都写进同一个云端后端，理论上天然跨机器共享。但需要在第二台机器
（如 Windows）上实测一遍：`machine_id.py` 能正常生成、`scope:machine` 的排除逻辑
在真实跨机器场景下行为正确。

### P6 — 语义近似匹配（**大概率不做**）
当前只能精确/子串匹配，措辞不同的同类教训匹配不上。真要解决需要 embedding，
但 `CLAUDE.md` 明令禁止引入独立向量库。除非有极强理由，否则接受这个限制。

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

## Codex / 其他 agent 接入

`skills/kb/SKILL.md` 是 Claude Code 专有格式，**Codex 不认**——它读的是仓库根目录的
[`AGENTS.md`](AGENTS.md)，那份文件覆盖了同样的内容并指向具体接口文档。

跨 agent 更可靠的路子是 MCP：`mcp/kb_mcp_server.py` 是标准的 stdio JSON-RPC MCP server
（零第三方依赖），任何支持 MCP 的客户端都能注册使用，配置时给它 `KB_BASE_URL` 和
`KB_API_TOKEN` 两个环境变量即可。具体配置语法各家不同，以你所用版本的文档为准；
Codex CLI 的一键注册命令（`codex mcp add ...`）和完整流程见 [`AGENTS.md`](AGENTS.md)。

## 新机器一条命令接入（推荐，跨项目自动生效）

在**任何一台从没碰过这个项目的新机器**上，跑一条命令就够了——装完之后这台机器上任何项目
目录、任何时候新开的 Claude Code 会话都会自动发现 `kb` 这个 skill，不用再管：

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/21CHAPPiE/Personal-knowledge-base/main/scripts/install_kb_skill.sh | bash
```

```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/21CHAPPiE/Personal-knowledge-base/main/scripts/install_kb_skill.ps1 | iex
```

会问你 `KB_BASE_URL`（这台机器要是跟知识库后端不是同一台，必须填公网地址）和
`KB_API_TOKEN`（没配置鉴权就留空），存进这台机器的 `~/.claude/kb-credentials`，以后这台机
器上所有项目共用，不会重复问。这一步是唯一躲不掉的手动动作——Skill 得是本机磁盘上真实存
在的文件，Claude Code 才能自动发现它，一台全新机器没法凭空知道要下载什么；跑完这一条命
令之后，往后就是真正意义上的"任何位置都自动"。

**这个仓库如果不是 public 的，上面两条命令拿不到东西**——`raw.githubusercontent.com`
对私有仓库的匿名请求是 404。这种情况改成直接从你自己的后端拉这两个安装脚本（后端已经
把它们和 Skill 内容本身都通过 `GET /api/skill/*` 开放出来了，`install.sh`/`install.ps1`
这两个接口本身不需要 token，就是为了解决"还没装上就已经要认证"这个先有鸡还是先有蛋的
问题）：

```bash
# Linux / macOS，把 <你的知识库地址> 换成 KB_BASE_URL 的实际值
curl -fsSL http://<你的知识库地址>/api/skill/install.sh | bash
```

```powershell
# Windows PowerShell
irm http://<你的知识库地址>/api/skill/install.ps1 | iex
```

这条路径全程不碰 GitHub，仓库公开与否都不影响使用。

下面是这条命令背后具体做了什么、以及不想用这条命令时的手动步骤：

## Skill 接入（Claude Code，自动发现，无需 MCP 注册）

仓库自带一个 Skill：[`skills/kb/SKILL.md`](skills/kb/SKILL.md)（内容与
`.claude/skills/kb/SKILL.md` 一致，后者是 Claude Code 官方文档里项目级 Skill 的首选扫描
路径）。它跟 MCP 效果一样，都是直接调 REST API，只是不需要 `claude mcp add` 这一步。

**两种安装范围，按你要用的场景选：**

- **只在这个仓库自己的会话里用**：什么都不用做，`.claude/skills/kb/SKILL.md` 已经在仓库里，
  Claude Code 在这个项目目录下启动新会话时会自动发现名为 `kb` 的 skill。
- **在别的项目里也要用**（比如你正在建的另一个项目，想让它的 Coding Agent 会话也能读写这
  同一个知识库）：项目级 Skill **只在这个仓库目录下生效，换一个项目目录不会被扫到**。要跨
  项目用，把同一份文件装到用户级全局目录：
  ```bash
  mkdir -p ~/.claude/skills/kb
  cp skills/kb/SKILL.md ~/.claude/skills/kb/SKILL.md
  ```
  装好之后，**任何**项目目录下新开的 Claude Code 会话都会自动发现 `kb` 这个 skill，不用在
  每个项目里重复放一份，也不用改那个项目自己的任何配置。

注意：skill 是在会话启动时扫描的，**已经打开的旧会话看不到新加的 skill，需要开一个新会话**才会出现在可用列表里——不管是项目级还是全局级都一样。

首次使用时它会在对话里问你 `KB_BASE_URL` 和 `KB_API_TOKEN`（后端没配置鉴权可以留空），
答案会存到 `~/.claude/kb-credentials`（用户主目录下，**不在仓库里**——这个仓库是 public 的，
任何密钥都不能提交进来），下次就不会再问——这一步是全局共享的，不管从哪个项目触发都只用
问一次。

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

# AGENTS.md

给 Codex 及其他读取 `AGENTS.md` 的 coding agent。Claude Code 读的是 `CLAUDE.md`
和 `skills/kb/SKILL.md`，内容等价，只是入口不同。

## 项目约定

动手改代码前先读 [`CLAUDE.md`](CLAUDE.md)——架构、编码规范、禁止事项都在那里。
几条最容易踩的：Python 3.9（不能用 `X | Y` 类型语法）、不引 ORM 和任何需要单独运行的
服务、tag 值里不能含英文逗号、`POST /api/knowledge` 是 multipart 不是 JSON。

## 这个知识库怎么用

它是一个 REST API（完整参考见 [`docs/api.md`](docs/api.md)），有两种接入方式：

**方式一：MCP（推荐）。** `mcp/kb_mcp_server.py` 是零依赖的标准 stdio MCP server，
任何支持 MCP 的 agent 都能用。注册后可直接调用 8 个工具：`kb_search`、`kb_get`、
`kb_add`、`kb_recent`、`project_get_context`、`project_append_context`、
`kb_lesson_match`、`kb_lesson_add`。

需要两个环境变量：`KB_BASE_URL`（后端地址）和 `KB_API_TOKEN`（后端配了鉴权时必需，
否则所有请求 401）。

**方式二：直接 curl 调 REST。** 不依赖 MCP 是否注册，做法和参数见
[`skills/kb/SKILL.md`](skills/kb/SKILL.md)——那份文档虽然是 Claude Code 的 skill 格式，
但正文就是纯粹的接口用法，对任何 agent 都适用，直接读即可。凭证从
`~/.claude/kb-credentials` 读（`KEY=VALUE` 格式，仓库外），没有就在对话里问用户要一次
并写进去。**绝不要把 token 写进仓库里的任何文件——这个仓库是 GitHub public 的。**

## 教训机制：动手前查，解决后写

这个知识库不只是笔记本，它记录已经踩过的坑，目的是同一个问题不解决第二遍。

**动手前**：做那些以前烧过时间的事情之前（跑不熟悉的命令、搭新服务或新框架、动
systemd/网络/权限/代理），先用即将执行的命令或预期报错去 `kb_lesson_match` 查一次。
**不是每个动作都查**——只在重复踩坑确实可能发生的地方查，否则开销大于收益。

**解决后**：非平凡的问题（花了不止一两轮才搞定）解决之后写一条教训。写之前先 match
一次，已有等价的就更新那条而不是写重复的。

教训的正文格式和 tag 规范见 `skills/kb/SKILL.md`，那里逐条讲了为什么每个字段都是承重的
（简单说：`【触发签名】`要短标记逐行写、逐字抄真实报错，因为检索是拿新报错去"包含"这些
标记；`【根因】`和`【解法】`会被分别打分，因为"这是什么错"和"怎么修"需要不同的那一半）。

## 命令失败时的自动兜底

`scripts/kb_shell_hook.sh` 通过 `BASH_ENV` 挂在 shell 层：任何命令返回非零时，它拿
命令文本去查一次知识库，命中就把教训打到 stderr——**不需要 agent 主动调用任何东西**，
提示会直接出现在你的命令输出里。装法是 `export BASH_ENV=~/.kb_shell_hook.sh`
（写进 `~/.profile` 和 `~/.bashrc`），`KB_HOOK=off` 可关闭。

它放在 shell 而不是某个 agent 的 hook 配置里，正是因为所有 agent 最终都通过 bash 执行
命令，绑定到某一家就只覆盖那一家。知识库不可达时它静默失败（2 秒超时），绝不阻塞干活。

注意它只能拿到**失败的命令文本**，拿不到 stderr（`trap ERR` 的限制），所以精度不如你
手动把报错原文喂给 `kb_lesson_match`。它是兜底，不是替代。

作用域选择是这套机制里最容易做错、代价也最大的一步：范围划窄了换个项目要重新踩一遍，
划宽了会被错误迁移到根本不成立的环境、制造新 bug。判断方法是问"换台机器还成立吗？换个
项目还成立吗？换个框架还成立吗？"，第一个"不成立"出现在哪一层就选上一层。

#!/usr/bin/env bash
# One-shot bootstrap for a brand-new machine that has never touched this
# knowledge base before: installs the `kb` Skill at user scope (so every
# Claude Code session, in every project, on this machine, discovers it from
# now on — no per-project setup, no MCP registration) and seeds the
# connection credentials so the skill doesn't have to ask on first use.
#
# The SKILL.md content is fetched from the knowledge base's own backend
# (GET /api/skill/kb), not from GitHub — this repo's visibility (public vs
# private) can change at any time, and the backend the install flow is
# already configuring is, by construction, a machine this script can reach.
# That's why KB_BASE_URL is asked for first, before anything is downloaded.
#
# This is the one manual step that can't be automated away: a Skill has to
# exist as a real file on a machine before Claude Code can discover it, and
# nothing can put that file there on a machine that has never run anything
# from this project. Everything after this one command is automatic.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/21CHAPPiE/Personal-knowledge-base/main/scripts/install_kb_skill.sh | bash
set -euo pipefail

SKILL_DIR="$HOME/.claude/skills/kb"
CREDS_FILE="$HOME/.claude/kb-credentials"

if [ -f "$CREDS_FILE" ]; then
  # shellcheck disable=SC1090
  source "$CREDS_FILE"
else
  echo "这台机器上第一次接这个知识库，填一下连接信息："
  read -r -p "KB_BASE_URL（跟知识库后端同一台机器就直接回车用默认值；不同机器要填公网地址）[http://127.0.0.1:8000]: " KB_BASE_URL
  read -r -p "KB_API_TOKEN（后端没配置鉴权就直接回车留空）: " KB_API_TOKEN
  KB_BASE_URL="${KB_BASE_URL:-http://127.0.0.1:8000}"
fi

AUTH_HEADER=()
if [ -n "${KB_API_TOKEN:-}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer $KB_API_TOKEN")
fi

mkdir -p "$SKILL_DIR"
if ! curl -fsSL "${AUTH_HEADER[@]}" "$KB_BASE_URL/api/skill/kb" -o "$SKILL_DIR/SKILL.md"; then
  echo "从 $KB_BASE_URL/api/skill/kb 拉取失败——检查 KB_BASE_URL 是不是填对了，" >&2
  echo "以及这个地址从这台机器上能不能连通（curl \"$KB_BASE_URL/health\" 先测一下）。" >&2
  exit 1
fi
echo "kb skill 已装到 $SKILL_DIR/SKILL.md —— 这台机器上任何项目目录新开的 Claude Code 会话都会自动发现它。"

if [ -f "$CREDS_FILE" ]; then
  echo "凭证文件已存在（$CREDS_FILE），不覆盖。"
  exit 0
fi

{
  echo "KB_BASE_URL=$KB_BASE_URL"
  echo "KB_API_TOKEN=${KB_API_TOKEN:-}"
} > "$CREDS_FILE"
chmod 600 "$CREDS_FILE"
echo "凭证已存到 $CREDS_FILE，以后这台机器上的每个项目都共用这一份，不会再问。"

---
name: kb
description: Search, read, and write to the user's personal knowledge base (个人知识库) via its REST API — daily notes, project knowledge, and per-project progress logs. Use whenever the user wants to save something to their knowledge base, recall or search past notes, or check/append a project's progress there.
---

# Personal Knowledge Base

This project exposes a REST API (full reference: `docs/api.md`). This skill calls
it directly with `curl` — no need for the `kb` MCP server to be registered in
this session; the effect is identical, since that server is itself just a thin
REST wrapper.

## Step 0 — get connection info (do this first, every time)

Read `~/.claude/kb-credentials` — a file in the user's home directory,
**outside this repo**. Never create or look for a credentials file inside the
project itself; this repo is public on GitHub and anything committed there is
permanent. Format is plain `KEY=VALUE` lines, e.g.:

```
KB_BASE_URL=http://127.0.0.1:8000
KB_API_TOKEN=some-token
```

- If the file exists, read both values from it. `KB_API_TOKEN` may be blank or
  absent if that backend has no token configured — that's normal, not an error.
- If the file does not exist, ask the user in the conversation:
  "知识库的 KB_BASE_URL 是什么？（不填默认 http://127.0.0.1:8000）" and
  "有没有 KB_API_TOKEN？（后端没配置鉴权可以留空）". Then write both values to
  `~/.claude/kb-credentials` and `chmod 600` it, so future sessions don't have
  to ask again.
- Never print the token back into the conversation once stored, and never
  write it anywhere under the project directory.

Every call below targets `$KB_BASE_URL<path>`. When `KB_API_TOKEN` is
non-empty, add header `Authorization: Bearer $KB_API_TOKEN` — the backend
rejects everything except `/health` with 401 once it has a token configured.

## Search

`GET /api/search?q=<query>&project_id=&type=&limit=` (`q` required, rest optional).

## Get one item / recent items

- `GET /api/knowledge/<id>`
- `GET /api/knowledge/recent?limit=<n>` (default 10)

## Add a knowledge item

`POST /api/knowledge` as **multipart/form-data** — a JSON body gets a 422 here,
this endpoint is multipart-only because it also accepts a file. Fields:
`title` (required, 1-200 chars), `content`, `type`
(`text`/`voice`/`screenshot`/`project_note`, default `text`), `project_id`
(optional), `tags` (repeat the field per tag), `source` (default `agent` for
anything this skill writes).

```bash
curl -s -X POST "$KB_BASE_URL/api/knowledge" \
  -H "Authorization: Bearer $KB_API_TOKEN" \
  -F "title=..." -F "content=..." -F "type=text" \
  -F "tags=..." -F "source=agent"
```

## Project context (get / append)

The user may refer to a project by name or numeric id — resolve it first:

1. Numeric ref: `GET /api/projects/<id>` directly.
2. Otherwise: `GET /api/projects`, match `name` case-insensitively.

Then:

- Get context: `GET /api/projects/<id>/context`
- Append progress: `POST /api/projects/<id>/context/append`, JSON body
  `{"content": "...", "title": "...", "source": "agent"}` (`title` optional).
  This endpoint does **not** accept `tags` — if the note needs tags, follow up
  with `PATCH /api/knowledge/<new_id>` and a `tags` array (this replaces the
  whole tag list, so re-read the item first if you need to merge rather than
  overwrite).

## Conventions this KB has adopted

- Log-style entries (progress updates, session summaries) get a
  `设备:<hostname>` tag via a follow-up `PATCH`, where `<hostname>` is the
  output of the `hostname` command on the machine actually doing the work —
  so entries can later be filtered per machine with `?tag=设备:<hostname>`.
- Never invent a "location" for an entry. If it matters, state what's
  actually known (which machine/environment produced it), not a guess.

## Errors

- `401 missing or invalid token` — token wrong or stale; delete
  `~/.claude/kb-credentials` and re-ask rather than guessing.
- `422` on `/api/knowledge` — almost always means it was sent as JSON instead
  of multipart form data.
- Full status/error code reference: `docs/api.md`.

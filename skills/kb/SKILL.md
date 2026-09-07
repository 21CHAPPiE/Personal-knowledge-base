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

## When a progress-log entry is worth writing at all

Two independent triggers, mirroring Claude's own cross-session memory system
exactly (see `docs/claude-memory.md` for the full writeup):

**Trigger 1 — the user explicitly asks for it.** If the user directly says
to record/save/log something, just do it — don't run it through the bar
below first. An explicit request already settles the question.

**Trigger 2 — you judge it worth logging on your own**, using the exact same
bar Claude's own cross-session memory uses. A note only qualifies if it is:

- **applicable** — it would actually change future behavior or a future
  decision, not just restate ambient status.
- **durable** — still true and useful beyond this one sitting, not a
  todo-list item or something obviously about to change.
- **legible** — full sentences a reader could pick up cold, one topic per
  entry, no shorthand or scratchpad prose.

Log: a completed feature/fix, a decision that shapes future work, a newly
discovered constraint (e.g. "this box only has ~3.6GB VRAM free"), or a
natural stopping point in a work session. Don't log: routine tool calls,
half-finished exploration, or anything failing any one of the three tests.

## Cost-tagging a progress-log entry

Every qualifying entry also gets a cost tag — what it cost in *cloud-model*
tokens (Claude / Codex / DeepSeek / whatever agent did the work), never the
local qwenlocal tokens, which are free and untracked here:

- If the write was produced by a delegated subagent, use the exact
  `subagent_tokens` number from that subagent's own completion report — this
  is precise and always available for delegated work.
- If the write was done directly in the main session, there is currently no
  tool that reports that session's own token usage for a specific span of
  work. **Do not invent a number.** Record it as
  `cost:unknown(direct-session)` instead of guessing.
- When an accurate figure actually matters, prefer routing the write itself
  through a delegated subagent specifically so the number is real.

Encode it as one more tag, alongside the `设备:` tag, in the form
`cost:<tokens>tok(<model>/<subagent|direct-session>)` — **use `/`, never `,`**,
inside the parens: tags are stored as a comma-joined string, so a `,` inside
one tag's value silently splits it into two separate tags (confirmed by
testing this exact convention). E.g. `cost:42537tok(claude-sonnet-5/subagent)`
or `cost:unknown(direct-session)`.

## Lessons — don't re-learn what's already been learned

The KB doubles as a record of problems already solved, so the same mistake
isn't paid for twice. A lesson is an ordinary knowledge item carrying a
`kind:lesson` tag; `GET /api/lessons/match` ranks them against your current
situation. Full design: `docs/lessons-system-plan.md`.

**Before acting — check.** For task categories that have burned time before
(running an unfamiliar command, standing up a new service or framework,
touching systemd / networking / permissions / proxies), call it first:

```bash
curl -s --get "$KB_BASE_URL/api/lessons/match" \
  -H "Authorization: Bearer $KB_API_TOKEN" \
  --data-urlencode "signature=<verbatim error text or command>" \
  --data-urlencode "os=linux" \
  --data-urlencode "machine=$(python3 scripts/machine_id.py)"
```

This is **not** a check to run before every action — the token cost would
exceed the benefit. Run it where repeat failure is actually plausible.

**After solving — record.** When something non-trivial got resolved (took more
than a round or two), write it down. Post it like any knowledge item
(multipart, `type=project_note`), with this body:

```
【触发签名】
<verbatim error string / failing command / symptom — copy exactly, never paraphrase>

【根因】
<the mechanism, not a restatement of the symptom>

【解法】
<what actually worked>

【不适用】
<where this explicitly does not hold; "暂无" if nothing>

【验证】
<when and how it was verified>
```

Verbatim matters: there is no vector search here (no vector DB, by project
rule), so retrieval leans on exact substrings. "网络有问题" can never be
matched against; `ImportError: Using SOCKS proxy` can.

**Tags on a lesson** — required: `kind:lesson`, and exactly one
`scope:machine|project|stack|universal`. Optional: `machine:<hostname>/<uuid6>`
(from `scripts/machine_id.py`; **required** when `scope:machine`),
`os:linux|windows|macos`, `stack:<name>` (repeatable), and `not:os:<name>` for
anti-scope.

**Choosing the scope is the part that matters.** Too narrow and it gets
re-learned on the next project; too broad and it gets misapplied somewhere it
was never true, creating a fresh bug. Ask what survives the change of context:

| scope | holds for | example |
|---|---|---|
| `machine` | this box only | this machine's `all_proxy=socks5://…` means localhost curl needs `--noproxy '*'` |
| `project` | this repo only | `GET /api/knowledge` caps `limit` at 100 |
| `stack` | any project on that framework | Vite behind a tunnel needs `server.allowedHosts` |
| `universal` | everywhere | browsers block `getUserMedia` outside a secure context |

Before adding, run a match first — if an equivalent lesson exists, `PATCH` that
one rather than creating a near-duplicate. (Tags replace wholesale on PATCH, so
re-read the item first.)

## Errors

- `401 missing or invalid token` — token wrong or stale; delete
  `~/.claude/kb-credentials` and re-ask rather than guessing.
- `422` on `/api/knowledge` — almost always means it was sent as JSON instead
  of multipart form data.
- Full status/error code reference: `docs/api.md`.

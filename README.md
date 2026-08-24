# Cross-Device Cloud Knowledge Base

A cross-device cloud knowledge base built on Supabase (Postgres + Storage) that stores project overviews, task progress, and knowledge notes.

- **PC side**: A local MCP Server enables Claude Code / Codex to automatically read progress, sync tasks, and record conclusions.
- **Mobile side**: A Feishu (Lark) bot ingests voice messages and screenshots into the knowledge base, and supports querying task progress.

**Design principles**: full-text search, single user, no-auth backend, keep the architecture as simple as possible.

## Usage

```bash
python start.py
```

The running result of `start.py` is saved in `start_result.txt`.

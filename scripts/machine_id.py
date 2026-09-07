#!/usr/bin/env python3
"""Print a stable identifier for this machine: <hostname>/<uuid-prefix>.

The uuid half is persisted at ~/.claude/machine-id on first run and never
changes after that. Hostnames alone are not enough — they collide across
machines and get renamed — but they are the half a human can read, so the
identifier carries both.

Used as the `machine:` tag on lessons (see docs/lessons-system-plan.md), which
is what keeps a machine-specific lesson from being applied on a machine where
it does not hold.
"""

import os
import socket
import sys
import uuid
from pathlib import Path

ID_PATH = Path.home() / ".claude" / "machine-id"


def load_or_create_uuid() -> str:
    try:
        existing = ID_PATH.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"machine_id: cannot read {ID_PATH}: {exc}", file=sys.stderr)
        raise

    generated = uuid.uuid4().hex
    ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    ID_PATH.write_text(generated + "\n", encoding="utf-8")
    os.chmod(str(ID_PATH), 0o600)
    return generated


def machine_id() -> str:
    host = socket.gethostname().strip() or "unknown-host"
    # '/' separates the two halves and ',' would break tag storage, so neither
    # may appear inside the hostname half.
    host = host.replace("/", "-").replace(",", "-")
    return "{}/{}".format(host, load_or_create_uuid()[:6])


if __name__ == "__main__":
    print(machine_id())

"""Deciding on proposals, and the rubric those decisions accumulate into.

A proposal is never applied silently: a decision is always recorded with who
made it, so the rubric can later be rebuilt from evidence rather than trusted
on faith. Human and automated decisions go through this same path — that is
the point, since the automated ones only exist to apply a standard the human
already demonstrated, and a standard nobody can audit is not a standard.

Resolved proposals are retagged rather than deleted. They leave the review
queue but stay readable, because spot-checking automated decisions requires
the decisions to still be there to check.
"""

import re
import sqlite3
from typing import List, Optional

from app.services.common import knowledge_out
from app.services.attachment_service import list_attachment_rows
from app.utils import parse_tags, utcnow_iso

PROPOSAL_TAG = "kind:proposal"
RESOLVED_TAG = "kind:proposal-resolved"
RUBRIC_TAG = "kind:review-rubric"
RUBRIC_TITLE = "待审判断标准（由你的实际决策归纳）"

CRITERIA_HEADING = "【判断标准】"
LOG_HEADING = "【决策记录】"

RUBRIC_SEED = """{criteria}
（还没有足够的决策记录，标准尚未归纳。先审几条，这里会根据你的实际判断自动写出来。）

{log}
""".format(criteria=CRITERIA_HEADING, log=LOG_HEADING)


class ProposalNotFound(Exception):
    def __init__(self, proposal_id: int):
        self.proposal_id = proposal_id


def _row(conn: sqlite3.Connection, knowledge_id: int):
    return conn.execute(
        "SELECT k.*, p.name AS project_name FROM knowledge_items k"
        " LEFT JOIN projects p ON p.id = k.project_id WHERE k.id = ?",
        (knowledge_id,),
    ).fetchone()


def get_or_create_rubric(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        "SELECT k.*, NULL AS project_name FROM knowledge_items k"
        " WHERE (',' || k.tags || ',') LIKE ? ORDER BY k.id LIMIT 1",
        ["%,{},%".format(RUBRIC_TAG)],
    ).fetchone()
    if row is not None:
        return row
    now = utcnow_iso()
    cur = conn.execute(
        "INSERT INTO knowledge_items (project_id, type, title, content, source, tags,"
        " summary, created_at, updated_at)"
        " VALUES (NULL, 'project_note', ?, ?, 'review', ?, NULL, ?, ?)",
        (RUBRIC_TITLE, RUBRIC_SEED, RUBRIC_TAG, now, now),
    )
    conn.commit()
    return _row(conn, cur.lastrowid)


def rubric_criteria(conn: sqlite3.Connection) -> str:
    """Just the criteria half — what an automated decision is judged against."""
    content = get_or_create_rubric(conn)["content"] or ""
    match = re.search(
        re.escape(CRITERIA_HEADING) + r"\s*\n(.*?)(?=\n\s*" + re.escape(LOG_HEADING) + r"|\Z)",
        content, re.S)
    return match.group(1).strip() if match else ""


def decision_log(conn: sqlite3.Connection) -> List[str]:
    content = get_or_create_rubric(conn)["content"] or ""
    match = re.search(re.escape(LOG_HEADING) + r"\s*\n(.*)\Z", content, re.S)
    if not match:
        return []
    return [ln.strip() for ln in match.group(1).splitlines() if ln.strip()]


def set_criteria(conn: sqlite3.Connection, criteria: str) -> dict:
    """Replace the derived half. The log below it is evidence and is never
    touched here — a criteria section that can't be checked against the
    decisions it came from is just an assertion."""
    rubric = get_or_create_rubric(conn)
    log_lines = decision_log(conn)
    content = "{}\n{}\n\n{}\n{}\n".format(
        CRITERIA_HEADING, criteria.strip(), LOG_HEADING, "\n".join(log_lines))
    conn.execute(
        "UPDATE knowledge_items SET content = ?, updated_at = ? WHERE id = ?",
        (content, utcnow_iso(), rubric["id"]),
    )
    conn.commit()
    return knowledge_out(_row(conn, rubric["id"]), attachments=[])


def _append_decision(conn: sqlite3.Connection, about: str, verdict: str,
                     note: str, by: str) -> None:
    rubric = get_or_create_rubric(conn)
    line = "{} | {} | {} | {} | {}".format(
        utcnow_iso(), about or "-", verdict, by, (note or "").replace("\n", " ").strip() or "-")
    content = (rubric["content"] or "").rstrip() + "\n" + line + "\n"
    conn.execute(
        "UPDATE knowledge_items SET content = ?, updated_at = ? WHERE id = ?",
        (content, utcnow_iso(), rubric["id"]),
    )


def _about_key(tags: List[str]) -> str:
    for tag in tags:
        if tag.startswith("about:"):
            return tag
    return ""


def referenced_ids(tags: List[str]) -> List[int]:
    """Item ids a logic-group proposal is about, read back out of its own
    dedup key (about:logic-127-128) rather than parsed out of Chinese prose."""
    key = _about_key(tags)
    match = re.match(r"about:logic-([\d\-]+)$", key)
    if not match:
        return []
    return sorted({int(part) for part in match.group(1).split("-") if part.isdigit()})


def _add_tag(conn: sqlite3.Connection, knowledge_id: int, tag: str) -> bool:
    row = _row(conn, knowledge_id)
    if row is None:
        return False
    tags = list(parse_tags(row["tags"]))
    if tag in tags:
        return False
    tags.append(tag)
    conn.execute(
        "UPDATE knowledge_items SET tags = ?, updated_at = ? WHERE id = ?",
        (",".join(tags), utcnow_iso(), knowledge_id),
    )
    return True


def decide(conn: sqlite3.Connection, proposal_id: int, verdict: str,
           note: Optional[str] = None, by: str = "human") -> dict:
    """Apply a verdict, record it, and take the proposal out of the queue.

    approve links the referenced items to each other by giving them the
    proposal's own key as a shared tag — the lightest thing that makes the
    connection real and findable without rewriting anything anyone wrote.
    """
    row = _row(conn, proposal_id)
    if row is None:
        raise ProposalNotFound(proposal_id)
    tags = list(parse_tags(row["tags"]))
    about = _about_key(tags)

    linked = []
    if verdict == "approve":
        for kid in referenced_ids(tags):
            if _add_tag(conn, kid, about):
                linked.append(kid)

    tags = [t for t in tags if t != PROPOSAL_TAG]
    for extra in (RESOLVED_TAG, "decision:" + verdict, "decided-by:" + by):
        if extra not in tags:
            tags.append(extra)
    conn.execute(
        "UPDATE knowledge_items SET tags = ?, updated_at = ? WHERE id = ?",
        (",".join(tags), utcnow_iso(), proposal_id),
    )
    _append_decision(conn, about, verdict, note or "", by)
    conn.commit()

    return {
        "proposal": knowledge_out(_row(conn, proposal_id),
                                  attachments=list_attachment_rows(conn, proposal_id)),
        "linked_items": linked,
    }


def pending(conn: sqlite3.Connection, limit: int = 50) -> List[dict]:
    rows = conn.execute(
        "SELECT k.*, p.name AS project_name FROM knowledge_items k"
        " LEFT JOIN projects p ON p.id = k.project_id"
        " WHERE (',' || k.tags || ',') LIKE ? ORDER BY k.id",
        ["%,{},%".format(PROPOSAL_TAG)],
    ).fetchall()
    out = []
    for row in rows:
        if PROPOSAL_TAG not in parse_tags(row["tags"]):
            continue  # LIKE on the joined string can over-match
        out.append(knowledge_out(row, attachments=[], content_preview=True))
        if len(out) >= limit:
            break
    return out


def referenced_items(conn: sqlite3.Connection, proposal_id: int) -> List[dict]:
    """The items a proposal is about, read live rather than from the snapshot
    baked into its text — the stored titles are truncated, and reviewing a
    grouping means reading what the items actually say."""
    row = _row(conn, proposal_id)
    if row is None:
        raise ProposalNotFound(proposal_id)
    out = []
    for kid in referenced_ids(parse_tags(row["tags"])):
        item = _row(conn, kid)
        if item is not None:
            out.append(knowledge_out(item, attachments=[]))
    return out

# kb_shell_hook.sh — surface a past lesson the moment a command fails.
#
# Everything else in this system depends on an agent remembering to look
# something up before acting, and remembering is exactly what it cannot be
# relied on to do. This hook removes the choice: the shell itself asks, at the
# only moment when the answer is certainly wanted.
#
# It lives in the shell rather than in one agent's hook config because every
# agent — Claude Code, Codex, Cursor, a person typing — ultimately runs commands
# through bash. An agent-specific mechanism would cover exactly one of them.
#
# INSTALL: export BASH_ENV=~/.kb_shell_hook.sh
#   BASH_ENV, not .bashrc: non-interactive shells never read .bashrc, and
#   `bash -c "..."` — which is how agents run everything — is non-interactive.
#   Put the export in ~/.profile and ~/.bashrc so both kinds of session and
#   anything they spawn inherit it.
#
# DISABLE: export KB_HOOK=off
#
# Reads KB_BASE_URL / KB_API_TOKEN from ~/.claude/kb-credentials.
#
# LIMITS, stated plainly:
#   - `trap ERR` gives the failing command and its exit code, never its stderr.
#     Capturing stderr would mean wrapping every command, which is too invasive
#     to be worth it, so the command text is the signature. Less precise than a
#     pasted error message, but it costs nothing and needs no cooperation.
#   - bash only. PowerShell needs its own equivalent.

if [ -n "$BASH_VERSION" ] && [ "${KB_HOOK:-on}" != "off" ]; then

__kb_hook_busy=0
__kb_hook_last=""
__kb_hook_last_at=0

__kb_lesson_on_error() {
    local code=$?
    local cmd="$BASH_COMMAND"

    # The hook's own curl failing must not re-enter the hook.
    [ "$__kb_hook_busy" = "1" ] && return 0
    case "$cmd" in *kb_lesson_on_error*|*lessons/match*) return 0 ;; esac

    # Commands whose non-zero exit is ordinary control flow, not a problem.
    case "${cmd%% *}" in
        grep|egrep|fgrep|rg|ag|test|'['|'[['|diff|cmp|which|type|command|pgrep|read|let|expr)
            return 0 ;;
    esac
    # 130 = Ctrl-C, 141 = SIGPIPE (e.g. `... | head`). Neither is a failure to explain.
    case "$code" in 130|141) return 0 ;; esac

    # Don't re-ask about the same command inside a retry loop.
    local now; now=$(date +%s)
    if [ "$cmd" = "$__kb_hook_last" ] && [ $((now - __kb_hook_last_at)) -lt 60 ]; then
        return 0
    fi
    __kb_hook_last="$cmd"
    __kb_hook_last_at="$now"

    local creds="$HOME/.claude/kb-credentials"
    [ -r "$creds" ] || return 0
    local base token
    base=$(sed -n 's/^KB_BASE_URL=//p' "$creds" | head -1)
    token=$(sed -n 's/^KB_API_TOKEN=//p' "$creds" | head -1)
    [ -n "$base" ] || return 0

    __kb_hook_busy=1
    local out
    # --max-time 2: a knowledge base that is slow or down must never become the
    # reason you cannot get work done. Silence is the correct failure mode here.
    out=$(curl -s --noproxy '*' --max-time 2 -G "$base/api/lessons/match" \
        ${token:+-H "Authorization: Bearer $token"} \
        --data-urlencode "signature=$cmd" \
        --data-urlencode "os=linux" \
        --data-urlencode "limit=2" 2>/dev/null \
        | python3 -c '
import json, sys
try:
    hits = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not hits:
    sys.exit(0)
print("\033[33m┌─ 知识库: 这个坑以前踩过 ─────────────\033[0m")
for h in hits[:2]:
    why = [r for r in h.get("match_reasons", []) if r == "signature" or "rerank" in r]
    print("\033[33m│\033[0m [#%s] %s  \033[2m%s\033[0m" % (h["id"], h["title"][:52], " ".join(why)))
    body = h.get("content", "")
    marker = "【解法】"
    if marker in body:
        fix = body.split(marker, 1)[1].strip().split("\n")[0]
        print("\033[33m│\033[0m   解法: %s" % fix[:88])
print("\033[33m└─ kb_get(<id>) 看完整教训\033[0m")
' 2>/dev/null)
    __kb_hook_busy=0

    [ -n "$out" ] && printf '%s\n' "$out" >&2
    return 0
}

set -o errtrace
trap '__kb_lesson_on_error' ERR

fi

# One-shot bootstrap for a brand-new Windows machine that has never touched
# this knowledge base before: installs the `kb` Skill at user scope (so
# every Claude Code session, in every project, on this machine, discovers
# it from now on) and seeds the connection credentials so the skill doesn't
# have to ask on first use.
#
# The SKILL.md content is fetched from the knowledge base's own backend
# (GET /api/skill/kb), not from GitHub — this repo's visibility (public vs
# private) can change at any time, and the backend this script is already
# configuring is, by construction, a machine it can reach. That's why
# KB_BASE_URL is asked for first, before anything is downloaded.
#
# This is the one manual step that can't be automated away: a Skill has to
# exist as a real file on a machine before Claude Code can discover it.
# Everything after this one command is automatic.
#
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/21CHAPPiE/Personal-knowledge-base/main/scripts/install_kb_skill.ps1 | iex

$ErrorActionPreference = "Stop"

$skillDir = Join-Path $env:USERPROFILE ".claude\skills\kb"
$credsFile = Join-Path $env:USERPROFILE ".claude\kb-credentials"

if (Test-Path $credsFile) {
    $creds = Get-Content $credsFile | ForEach-Object {
        if ($_ -match "^([A-Z_]+)=(.*)$") { @{ $matches[1] = $matches[2] } }
    }
    $baseUrl = ($creds | Where-Object { $_.ContainsKey("KB_BASE_URL") } | Select-Object -First 1)["KB_BASE_URL"]
    $token = ($creds | Where-Object { $_.ContainsKey("KB_API_TOKEN") } | Select-Object -First 1)["KB_API_TOKEN"]
} else {
    Write-Host "这台机器上第一次接这个知识库，填一下连接信息："
    $baseUrl = Read-Host "KB_BASE_URL（这台机器和知识库后端不是同一台，一定要填公网地址；同一台就直接回车用默认值）[http://127.0.0.1:8000]"
    $token = Read-Host "KB_API_TOKEN（后端没配置鉴权就直接回车留空）"
    if ([string]::IsNullOrWhiteSpace($baseUrl)) { $baseUrl = "http://127.0.0.1:8000" }
}

$headers = @{}
if (-not [string]::IsNullOrWhiteSpace($token)) { $headers["Authorization"] = "Bearer $token" }

New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
try {
    Invoke-WebRequest -Uri "$baseUrl/api/skill/kb" -Headers $headers -OutFile (Join-Path $skillDir "SKILL.md")
} catch {
    Write-Host "从 $baseUrl/api/skill/kb 拉取失败——检查 KB_BASE_URL 是不是填对了，以及这个地址从这台机器上能不能连通。" -ForegroundColor Red
    throw
}
Write-Host "kb skill 已装到 $skillDir\SKILL.md —— 这台机器上任何项目目录新开的 Claude Code 会话都会自动发现它。"

if (Test-Path $credsFile) {
    Write-Host "凭证文件已存在（$credsFile），不覆盖。"
    exit 0
}

$credsDir = Split-Path $credsFile -Parent
New-Item -ItemType Directory -Force -Path $credsDir | Out-Null
"KB_BASE_URL=$baseUrl`nKB_API_TOKEN=$token" | Set-Content -Path $credsFile -Encoding UTF8
Write-Host "凭证已存到 $credsFile，以后这台机器上的每个项目都共用这一份，不会再问。"

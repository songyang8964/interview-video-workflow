<#
.SYNOPSIS
  一键安装 interview-video-workflow，支持 Claude Code 和 Codex。

  做五件事：
    1. 检查并安装依赖：Python、FFmpeg（缺什么用 winget 装什么），以及 Python 包 pillow、numpy
    2. 新建工作文件夹（默认 文档\访谈长文），把 tools 复制进去，并下载 yt-dlp.exe
    3. 把四个写作技能复制到 AI 助手的技能目录，填好路径；另外下载深度润色用的 adversarial-polish
    4. 在工作文件夹里生成项目规则：Claude Code 读 CLAUDE.md，Codex 读 AGENTS.md；已有的不覆盖
    5. 最后逐项检查，告诉你哪些就绪、哪些还缺

  默认自动判断：电脑上装了哪个助手就装给哪个，两个都装了就都装。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -WorkDir "D:\访谈长文"
  powershell -ExecutionPolicy Bypass -File install.ps1 -Target claude
  可选：-Target auto|claude|codex|both   -SkipDeps（跳过依赖安装，只复制文件）
#>
param(
    [string]$WorkDir = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) '访谈长文'),
    [ValidateSet('auto', 'claude', 'codex', 'both')][string]$Target = 'auto',
    [string]$ClaudeSkillsDir = (Join-Path $env:USERPROFILE '.claude\skills'),
    [string]$CodexSkillsDir = (Join-Path $env:USERPROFILE '.codex\skills'),
    [switch]$SkipDeps
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = $PSScriptRoot
$utf8 = New-Object System.Text.UTF8Encoding $false

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  [好] $text" -ForegroundColor Green }
function Bad($text) { Write-Host "  [缺] $text" -ForegroundColor Yellow }

function Refresh-Path {
    # winget 装完的新程序，要重新读取 PATH 才找得到
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Test-Cmd($name, [string[]]$argv) {
    # 返回命令能否正常运行（Windows 自带的 python 占位程序会运行失败，也算没有）
    $ErrorActionPreference = 'Continue'
    try { & $name @argv *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}

function Install-WithWinget($id, $label) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Bad "没有 winget，无法自动安装 $label。请手动安装后重新运行本脚本"
        return
    }
    Write-Host "  正在安装 $label（可能要几分钟，期间可能弹出权限确认）..."
    $ErrorActionPreference = 'Continue'
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent | Out-Host
    Refresh-Path
}

function Find-Codex {
    $c = (Get-Command codex -ErrorAction SilentlyContinue).Source
    if ($c) { return $c }
    $bundled = Join-Path $env:USERPROFILE '.codex\.sandbox-bin\codex.exe'   # Codex 桌面版自带的命令行
    if (Test-Path $bundled) { return $bundled }
    return $null
}

# ---------------------------------------------------------------- 装给谁
$hasClaude = (Test-Path (Join-Path $env:USERPROFILE '.claude')) -or [bool](Get-Command claude -ErrorAction SilentlyContinue)
$hasCodex = (Test-Path (Join-Path $env:USERPROFILE '.codex')) -or [bool](Find-Codex)
switch ($Target) {
    'claude' { $useClaude = $true; $useCodex = $false }
    'codex' { $useClaude = $false; $useCodex = $true }
    'both' { $useClaude = $true; $useCodex = $true }
    default {
        $useClaude = $hasClaude; $useCodex = $hasCodex
        if (-not ($useClaude -or $useCodex)) { $useClaude = $true; $useCodex = $true }   # 都没检测到：两边都装，先装好也无妨
    }
}
$agents = @()
if ($useClaude) { $agents += [pscustomobject]@{ Name = 'Claude Code'; Skills = $ClaudeSkillsDir; Rules = 'CLAUDE.md' } }
if ($useCodex) { $agents += [pscustomobject]@{ Name = 'Codex'; Skills = $CodexSkillsDir; Rules = 'AGENTS.md' } }
Write-Host ("安装给：" + (($agents | ForEach-Object { $_.Name }) -join '、'))

# ---------------------------------------------------------------- 1. 依赖
if (-not $SkipDeps) {
    Step '1/5 检查依赖'
    if (Test-Cmd python @('--version')) { Ok ("Python：" + (python --version 2>&1)) }
    else { Install-WithWinget 'Python.Python.3.12' 'Python 3.12' }

    if (Test-Cmd ffmpeg @('-version')) { Ok 'FFmpeg 已安装' }
    else { Install-WithWinget 'Gyan.FFmpeg' 'FFmpeg' }

    if (Test-Cmd python @('--version')) {
        Write-Host '  安装 Python 包 pillow、numpy ...'
        $ErrorActionPreference = 'Continue'
        python -m pip install --user --quiet --disable-pip-version-check pillow numpy | Out-Host
        $ErrorActionPreference = 'Stop'
    }
} else {
    Step '1/5 跳过依赖安装（-SkipDeps）'
}

# ---------------------------------------------------------------- 2. 工作文件夹
Step "2/5 准备工作文件夹：$WorkDir"
$toolsDir = Join-Path $WorkDir 'tools'
New-Item -ItemType Directory -Force $toolsDir | Out-Null
Copy-Item (Join-Path $repo 'tools\*') $toolsDir -Force
Ok '已复制 tools'
$ytdlp = Join-Path $toolsDir 'yt-dlp.exe'
if (Test-Path $ytdlp) { Ok '已有 yt-dlp.exe' }
else {
    Write-Host '  下载 yt-dlp.exe ...'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe' -OutFile $ytdlp -UseBasicParsing
        Ok '已下载 yt-dlp.exe'
    } catch { Bad "yt-dlp.exe 下载失败：$($_.Exception.Message)。可以手动下载后放进 $toolsDir" }
}

# ---------------------------------------------------------------- 3. 技能
Step '3/5 安装技能'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
foreach ($a in $agents) {
    Write-Host "  [$($a.Name)] $($a.Skills)"
    New-Item -ItemType Directory -Force $a.Skills | Out-Null
    $backup = Join-Path (Split-Path $a.Skills -Parent) "skills_backup\$stamp"
    foreach ($skill in Get-ChildItem (Join-Path $repo 'skills') -Directory) {
        $dest = Join-Path $a.Skills $skill.Name
        if (Test-Path $dest) {
            # 备份到技能目录之外，免得旧版本被当成同名技能再加载一次
            New-Item -ItemType Directory -Force $backup | Out-Null
            Move-Item $dest (Join-Path $backup $skill.Name)
        }
        Copy-Item $skill.FullName $dest -Recurse
        Get-ChildItem $dest -Recurse -Filter '*.md' | ForEach-Object {
            $text = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8).Replace('<技能目录>', $a.Skills)
            [IO.File]::WriteAllText($_.FullName, $text, $utf8)
        }
    }
    if (Test-Path $backup) { Write-Host "    旧版技能已备份到 $backup" }
    Ok "$($a.Name)：interview-video、interview-analysis、interview-writing、writing-style"

    # 可选：--deep-polish 要用的对抗式打磨技能，从原作者仓库下载，不随本仓库分发
    $ap = Join-Path $a.Skills 'adversarial-polish'
    if (Test-Path (Join-Path $ap 'SKILL.md')) { Ok "$($a.Name)：adversarial-polish（已有）" }
    else {
        try {
            New-Item -ItemType Directory -Force $ap | Out-Null
            Invoke-WebRequest 'https://raw.githubusercontent.com/jimliu/illustrated-agent-skills/main/skills/adversarial-polish/SKILL.md' -OutFile (Join-Path $ap 'SKILL.md') -UseBasicParsing
            Ok "$($a.Name)：adversarial-polish（深度润色用，来自 jimliu/illustrated-agent-skills）"
        } catch {
            Remove-Item -Recurse -Force $ap -ErrorAction SilentlyContinue
            Bad 'adversarial-polish 下载失败。不影响正常使用，只是 --deep-polish 用不了'
        }
    }
}

# ---------------------------------------------------------------- 4. 项目规则
Step '4/5 生成项目规则'
$rules = [IO.File]::ReadAllText((Join-Path $repo 'docs\项目规则.md'), [Text.Encoding]::UTF8)
$rules = $rules -replace '^# .*', '# 访谈长文项目说明'
foreach ($a in $agents) {
    $file = Join-Path $WorkDir $a.Rules
    if (Test-Path $file) { Ok "$($a.Rules) 已存在，保留你的版本，没有覆盖" }
    else { [IO.File]::WriteAllText($file, $rules, $utf8); Ok "已生成 $($a.Rules)（$($a.Name) 读这个文件）" }
}

# ---------------------------------------------------------------- 5. 检查
Step '5/5 检查结果'
Refresh-Path
$allOk = $true
if (Test-Cmd python @('--version')) { Ok 'Python' } else { Bad 'Python 未就绪：安装后重新打开 PowerShell 再运行本脚本'; $allOk = $false }
if (Test-Cmd ffmpeg @('-version')) { Ok 'FFmpeg' } else { Bad 'FFmpeg 未就绪：安装后重新打开 PowerShell 再运行本脚本'; $allOk = $false }
if (Test-Cmd python @('-c', 'import PIL, numpy')) { Ok 'pillow、numpy' } else { Bad 'Python 包未就绪：运行 python -m pip install --user pillow numpy'; $allOk = $false }
if (Test-Path $ytdlp) { Ok 'yt-dlp' } else { Bad 'yt-dlp.exe 不在 tools 里'; $allOk = $false }
if ($useClaude) {
    if ($hasClaude) { Ok 'Claude Code' } else { Bad '没找到 Claude Code：请安装 Claude 桌面版或 Claude Code 并登录'; $allOk = $false }
}
if ($useCodex) {
    if ($hasCodex) { Ok 'Codex' } else { Bad '没找到 Codex：请安装 Codex 桌面版并登录'; $allOk = $false }
}
if ($useClaude -and -not (Find-Codex)) {
    Write-Host '  （提示）盲读脚本 blind_read.ps1 要用 Codex。只用 Claude Code 的话不需要它，盲读会交给子 agent。'
}

Write-Host ''
if ($allOk) { Write-Host '安装完成。接下来：' -ForegroundColor Green }
else {
    Write-Host '还有几项没就绪（见上面的 [缺]）。处理完可以重新运行本脚本，已完成的部分会跳过。' -ForegroundColor Yellow
    Write-Host '其余部分已装好。接下来：'
}
Write-Host "  1. 完全退出并重新打开你的 AI 助手（Claude 或 Codex），让它加载新技能"
Write-Host "  2. 在助手里打开文件夹：$WorkDir"
Write-Host '  3. 发一句：用 interview-video 技能把这个访谈整理成中文长文：<YouTube 链接>'

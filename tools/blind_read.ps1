<#
.SYNOPSIS
  第 4b 步"盲读挑刺"：每章起一个独立的 codex exec 进程，只把这一章的中文正文给它，挑出读着像翻译、看不懂、节奏差的段落。

  每个进程都是全新上下文，看不到英文原文、润色记录和其他章节，这正是盲读需要的隔离。
  结果合并写入 <素材目录>\盲读挑刺.json：{"01": [...], "02": [...]}；某章解析失败时保留原始输出。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\blind_read.ps1 -Dir "素材\Edward_Snowden_JRE_PhoneSpying"
  可选：-Chapters 01,03（只审这几章）  -Model gpt-5.6-sol  -Codex <codex.exe 路径>
#>
param(
    [Parameter(Mandatory = $true)][string]$Dir,
    [string[]]$Chapters = @(),
    [string]$Model = 'gpt-5.6-sol',
    [string]$Codex = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = New-Object System.Text.UTF8Encoding $false   # 管道传给 codex 的中文按 UTF-8 编码

if (-not $Codex) {
    $onPath = (Get-Command codex -ErrorAction SilentlyContinue).Source
    $bundled = Join-Path $env:USERPROFILE '.codex\.sandbox-bin\codex.exe'   # Codex 桌面版自带的命令行
    $Codex = if ($onPath) { $onPath } elseif (Test-Path $bundled) { $bundled } else { '' }
}
if (-not $Codex) { throw '找不到 codex：安装 Codex 桌面版或 npm i -g @openai/codex，或用 -Codex 指定路径' }

$Dir = (Resolve-Path $Dir).Path
$chapterDir = Join-Path $Dir 'chapters'
$files = Get-ChildItem $chapterDir -Filter '*.md' | Where-Object { $_.BaseName -match '^\d+$' } | Sort-Object Name
if ($Chapters.Count) { $files = $files | Where-Object { $Chapters -contains $_.BaseName } }
if (-not $files) { throw "在 $chapterDir 下没有找到 NN.md 章节文件" }

$prompt = Get-Content (Join-Path $PSScriptRoot 'blind_read_prompt.md') -Raw -Encoding UTF8
$outDir = Join-Path $Dir '盲读挑刺'
New-Item -ItemType Directory -Force $outDir | Out-Null
# 在空目录里运行，进一步避免审读者顺手读到英文逐字稿
$sandboxCwd = Join-Path $env:TEMP ('blind_read_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $sandboxCwd | Out-Null

$result = [ordered]@{}
foreach ($f in $files) {
    $text = Get-Content $f.FullName -Raw -Encoding UTF8
    $text = [regex]::Replace($text, '<!--.*?-->', '', 'Singleline')   # 去掉写作者留下的 HTML 注释
    $out = Join-Path $outDir ($f.BaseName + '.txt')
    Write-Host "盲读 $($f.Name) ..."
    if (Test-Path $out) { Remove-Item $out }
    # codex 会往 stderr 写进度信息；Windows PowerShell 5.1 在 Stop 模式下会把它当成错误，这里临时放宽
    $ErrorActionPreference = 'Continue'
    ($prompt + "`n`n" + $text) | & $Codex exec -m $Model -s read-only --skip-git-repo-check --ephemeral -C $sandboxCwd -o $out 2>&1 | Out-Null
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -or -not (Test-Path $out)) { Write-Warning "$($f.Name)：codex 没有返回结果（退出码 $code）。可用 -Model 换一个模型重试"; continue }
    $raw = (Get-Content $out -Raw -Encoding UTF8).Trim()
    $json = [regex]::Match($raw, '\[[\s\S]*\]').Value
    try {
        # 用 ArrayList 存，避免 Windows PowerShell 5.1 把数组序列化成 {"value":…,"Count":…}
        $items = New-Object System.Collections.ArrayList
        foreach ($i in ($json | ConvertFrom-Json)) { [void]$items.Add($i) }
        $result[$f.BaseName] = $items
        Write-Host "  挑出 $($items.Count) 处"
    } catch {
        $result[$f.BaseName] = @{ 原始输出 = $raw }
        Write-Warning "$($f.Name)：输出不是合法 JSON，已保留原文"
    }
}
Remove-Item -Recurse -Force $sandboxCwd

$target = Join-Path $Dir '盲读挑刺.json'
$jsonText = $result | ConvertTo-Json -Depth 6
[IO.File]::WriteAllText($target, $jsonText, (New-Object System.Text.UTF8Encoding $false))
Write-Host "已写出 $target"

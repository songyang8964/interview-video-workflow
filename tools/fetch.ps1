<#
.SYNOPSIS
  下载 YouTube 访谈的元数据、字幕和视频，并生成 transcript.md。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\fetch.ps1 -Url "https://www.youtube.com/watch?v=xxxx" -Slug "Rupert_Lowe_JoeRogan_2524"
  可选：-Lang en  -SkipVideo  -CookiesFrom chrome  -YtDlp <yt-dlp.exe 路径>（默认依次找 tools\yt-dlp.exe、PATH）

  产物都在 素材\<Slug>\ 下：
    source.info.json / source.<lang>*.json3 / video.mp4 / transcript.md
#>
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $true)][string]$Slug,
    [string]$Lang = 'en',
    [switch]$SkipVideo,
    [string]$CookiesFrom = '',
    [string]$YtDlp = ''
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$dir = Join-Path $root "素材\$Slug"
New-Item -ItemType Directory -Force $dir | Out-Null
if (-not $YtDlp) {
    $local = Join-Path $PSScriptRoot 'yt-dlp.exe'
    $YtDlp = if (Test-Path $local) { $local } else { (Get-Command yt-dlp -ErrorAction SilentlyContinue).Source }
}
if (-not $YtDlp -or -not (Test-Path $YtDlp)) { throw "找不到 yt-dlp：把 yt-dlp.exe 放到 tools\ 下、加入 PATH，或用 -YtDlp 指定路径" }

$common = @('--no-playlist', '--encoding', 'utf-8', '-P', $dir, '-o', 'source.%(ext)s')
if ($CookiesFrom) { $common += @('--cookies-from-browser', $CookiesFrom) }

Write-Host "[1/3] 元数据与字幕 → $dir"
& $YtDlp @common --skip-download --write-info-json --write-subs --write-auto-subs `
    --sub-langs "$Lang-orig,$Lang,$Lang-*" --sub-format json3 $Url
if ($LASTEXITCODE) { throw "yt-dlp 获取字幕失败（退出码 $LASTEXITCODE）。可尝试：先运行 `"$YtDlp -U`" 更新；或加 -CookiesFrom chrome" }

if (-not $SkipVideo) {
    Write-Host "[2/3] 视频（720p 以内，供截图用）"
    $videoArgs = @('--no-playlist', '-P', $dir, '-o', 'video.%(ext)s',
        '-f', 'bv*[height<=720][ext=mp4]+ba[ext=m4a]/bv*[height<=720]+ba/b[height<=720]/b',
        '--merge-output-format', 'mp4', '--concurrent-fragments', '4')
    if ($CookiesFrom) { $videoArgs += @('--cookies-from-browser', $CookiesFrom) }
    & $YtDlp @videoArgs $Url
    if ($LASTEXITCODE) { Write-Warning "视频下载失败（退出码 $LASTEXITCODE）。字幕已就绪，可先写作，配图前再用 -CookiesFrom 重试。" }
} else {
    Write-Host "[2/3] 跳过视频"
}

Write-Host "[3/3] 生成逐字稿"
python -P (Join-Path $PSScriptRoot 'transcript.py') $dir --lang $Lang
if ($LASTEXITCODE) { throw "transcript.py 失败" }
Write-Host "完成：$dir"

# Скачивает GGUF-модель для llama.cpp в docker/models/
#
# Использование (из папки docker/):
#   .\download-model.ps1
#   .\download-model.ps1 -Repo "unsloth/Qwen3.5-9B-GGUF" -File "Qwen3.5-9B-Q4_K_M.gguf"
#
# После скачивания не забудь указать файл в .env (MODEL_FILE=/models/<имя файла>)

param(
    [string]$Repo = "unsloth/gemma-4-E4B-it-qat-GGUF",
    [string]$File = "gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf"
)

$ErrorActionPreference = "Stop"
$modelsDir = Join-Path $PSScriptRoot "models"
New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null
$dest = Join-Path $modelsDir $File

if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 1MB)) {
    Write-Host ("Уже скачано: {0} ({1:N1} GB)" -f $dest, ((Get-Item $dest).Length / 1GB))
    exit 0
}

$url = "https://huggingface.co/$Repo/resolve/main/$File"
Write-Host "Скачиваю: $Repo/$File"
Write-Host "  откуда: $url"
Write-Host "  куда:   $dest"

# curl входит в Windows 10/11: -L — следовать редиректам, -C - — продолжать обрыв,
# --retry — повторы при сетевых сбоях, -sS — без прогресса (удобно в фоне)
& curl.exe -sS -L -C - --retry 8 --retry-delay 3 -o $dest $url
if ($LASTEXITCODE -ne 0) {
    Write-Host "ОШИБКА: код $LASTEXITCODE"
    Write-Host "Если репозиторий gated (401/403) — попробуй другой -Repo/-File,"
    Write-Host "например: -Repo 'unsloth/gemma-4-E4B-it-GGUF' -File 'gemma-4-E4B-it-Q4_K_M.gguf'"
    exit $LASTEXITCODE
}

Write-Host ("Готово: {0:N1} GB" -f ((Get-Item $dest).Length / 1GB))

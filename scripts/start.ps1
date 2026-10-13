# 在项目目录启动，不修改用户的全局环境。
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.conda/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '请先按 README 创建项目 Anaconda 环境。'
}
Set-Location -LiteralPath $taskRoot
& $taskPython -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --workers 1

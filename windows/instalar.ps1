# Instalador del receptor de Alertas Rivas
$ErrorActionPreference = 'Stop'
$Dir = Join-Path $env:LOCALAPPDATA 'AlertasRivas'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

Write-Host ''
Write-Host '=== Instalación de Alertas Rivas ===' -ForegroundColor Cyan
$topic = $args[0]
if (-not $topic) { $topic = Read-Host 'Pega el nombre del canal de ntfy (el mismo que en el móvil)' }
$topic = $topic.Trim()
if ($topic -notmatch '^[A-Za-z0-9_-]{6,64}$') { throw 'El nombre del canal no es válido.' }

# Parar una copia anterior si está funcionando
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*AlertasRivas*receptor.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Copy-Item -Path (Join-Path $PSScriptRoot 'receptor.ps1') -Destination $Dir -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'probar.ps1') -Destination $Dir -Force
@{ topic = $topic; server = 'https://ntfy.sh' } | ConvertTo-Json | Set-Content -Path (Join-Path $Dir 'config.json') -Encoding UTF8

$ps = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$argsReceptor = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Dir\receptor.ps1`""

# Arranque automático al iniciar sesión
$startup = [Environment]::GetFolderPath('Startup')
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $startup 'Alertas Rivas.lnk'))
$lnk.TargetPath = $ps
$lnk.Arguments = $argsReceptor
$lnk.WorkingDirectory = $Dir
$lnk.Description = 'Receptor de alertas meteorológicas AEMET (Madrid, Corredor, Rivas)'
$lnk.Save()

Start-Process -FilePath $ps -ArgumentList $argsReceptor -WindowStyle Hidden
Write-Host ''
Write-Host 'Listo. El receptor está funcionando y arrancará solo cada vez que inicies sesión.' -ForegroundColor Green
Write-Host "Carpeta: $Dir"
Write-Host 'Para probarlo: ejecuta probar.ps1 (envía las 3 alertas de prueba).'

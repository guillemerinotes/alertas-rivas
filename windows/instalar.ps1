# Instalador del receptor de Alertas Rivas
$ErrorActionPreference = 'Stop'
$Dir = Join-Path $env:LOCALAPPDATA 'AlertasRivas'
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

Write-Host ''
Write-Host '=== Instalación del receptor RIV-Alert ===' -ForegroundColor Cyan
$topic = $args[0]
$archivoCanal = Join-Path $PSScriptRoot 'canal.txt'
if (-not $topic -and (Test-Path $archivoCanal)) { $topic = (Get-Content $archivoCanal -Raw).Trim() }
$cfgViejo = Join-Path $Dir 'config.json'
if (-not $topic -and (Test-Path $cfgViejo)) { try { $topic = (Get-Content $cfgViejo -Raw -Encoding UTF8 | ConvertFrom-Json).topic } catch {} }
if (-not $topic) { $topic = Read-Host 'Pega el nombre del canal de ntfy (el mismo que en el móvil)' }
$topic = $topic.Trim()
if ($topic -notmatch '^[A-Za-z0-9_-]{6,64}$') { throw 'El nombre del canal no es válido.' }

# Parar una copia anterior si está funcionando
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*AlertasRivas*receptor.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Copy-Item -Path (Join-Path $PSScriptRoot 'receptor.ps1') -Destination $Dir -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'probar.ps1') -Destination $Dir -Force
Copy-Item -Path (Join-Path $PSScriptRoot 'lanzador.vbs') -Destination $Dir -Force
foreach ($x in 'situacion.ps1') {
    $src = Join-Path $PSScriptRoot $x
    if (Test-Path $src) { Copy-Item -Path $src -Destination $Dir -Force }
}
@{ topic = $topic; server = 'https://ntfy.sh' } | ConvertTo-Json | Set-Content -Path (Join-Path $Dir 'config.json') -Encoding UTF8

$ps = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$argsReceptor = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Dir\receptor.ps1`""

# Arranque automático al iniciar sesión
$startup = [Environment]::GetFolderPath('Startup')
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut((Join-Path $startup 'Alertas Rivas.lnk'))
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
$lnk.TargetPath = $wscript
$lnk.Arguments = "`"$Dir\lanzador.vbs`""
$lnk.WorkingDirectory = $Dir
$lnk.Description = 'Receptor RIV-Alert (Protección Civil Rivas)'
$lnk.Save()

# Accesos directos en el escritorio
$desk = [Environment]::GetFolderPath('Desktop')
# El antiguo "Mandar comunicado" solo publicaba en tu canal personal: ahora se usa la app
$viejo = Join-Path $desk 'RIV-Alert · Mandar comunicado.lnk'
if (Test-Path $viejo) { Remove-Item $viejo -Force }
Set-Content -Path (Join-Path $desk 'RIV-Alert (app).url') -Encoding ASCII -Value "[InternetShortcut]`r`nURL=https://riv-alert.vercel.app/`r`n"
$s = $ws.CreateShortcut((Join-Path $desk 'RIV-Alert · Situación.lnk'))
$s.TargetPath = $ps
$s.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Dir\situacion.ps1`""
$s.WorkingDirectory = $Dir
$s.IconLocation = "$env:WINDIR\System32\shell32.dll,221"
$s.Save()

# Vigilante: cada 5 minutos comprueba que el receptor está funcionando y, si no, lo arranca
& schtasks.exe /Create /F /SC MINUTE /MO 5 /TN 'RIV-Alert receptor' /TR "`"$wscript`" `"$Dir\lanzador.vbs`"" | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host 'Vigilante de Windows creado (revisa el receptor cada 5 min).' -ForegroundColor Green }
else { Write-Host 'No se pudo crear el vigilante de Windows; el receptor arrancará igualmente al iniciar sesión.' -ForegroundColor Yellow }

Start-Process -FilePath $wscript -ArgumentList "`"$Dir\lanzador.vbs`""
Write-Host ''
Write-Host 'Listo. El receptor está funcionando y arrancará solo cada vez que inicies sesión.' -ForegroundColor Green
Write-Host "Carpeta: $Dir"
Write-Host 'En el escritorio tienes: RIV-Alert · Situación y RIV-Alert (app) para comunicados.'

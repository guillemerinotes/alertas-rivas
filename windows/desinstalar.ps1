# Desinstala el receptor de Alertas Rivas
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*AlertasRivas*receptor.ps1*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'Alertas Rivas.lnk') -ErrorAction SilentlyContinue
Remove-Item (Join-Path $env:LOCALAPPDATA 'AlertasRivas') -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'Receptor desinstalado.'

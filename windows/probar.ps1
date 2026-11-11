# Envía 3 alertas de prueba (Madrid, Corredor y Rivas) al canal de ntfy.
# Llegan al PC y al móvil a la vez.
$ErrorActionPreference = 'Stop'
$Dir = Join-Path $env:LOCALAPPDATA 'AlertasRivas'
$cfg = Get-Content (Join-Path $Dir 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$server = if ($cfg.server) { $cfg.server.TrimEnd('/') } else { 'https://ntfy.sh' }
$pruebas = @(
    @{ title = 'MADRID · PRUEBA · Aviso AMARILLO · Vientos'; priority = 3; tags = @('yellow_circle', 'nivel-madrid', 'evento-prueba'); message = 'Prueba del nivel MADRID. No hay ningún aviso real.' },
    @{ title = 'CORREDOR DEL HENARES · PRUEBA · Aviso NARANJA · Lluvias'; priority = 4; tags = @('orange_circle', 'nivel-corredor', 'evento-prueba'); message = 'Prueba del nivel CORREDOR. No hay ningún aviso real.' },
    @{ title = '⚠️ RIVAS · PRUEBA · Aviso ROJO · Tormentas'; priority = 5; tags = @('red_circle', 'nivel-rivas', 'evento-prueba'); message = 'Prueba de la ALERTA DE RIVAS. No hay ningún aviso real.' }
)
foreach ($p in $pruebas) {
    $p.topic = $cfg.topic
    $p.click = 'https://www.aemet.es/es/eltiempo/prediccion/avisos?k=mad'
    $body = [System.Text.Encoding]::UTF8.GetBytes(($p | ConvertTo-Json -Compress))
    Invoke-RestMethod -Uri $server -Method Post -Body $body -ContentType 'application/json; charset=utf-8' | Out-Null
    Start-Sleep -Seconds 3
}
Write-Host 'Enviadas 3 alertas de prueba.'

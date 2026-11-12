# Envía 3 alertas de prueba de RIV-Alert (amarillo, naranja y rojo) al canal de ntfy.
# Llegan al PC y al móvil a la vez.
$ErrorActionPreference = 'Stop'
$Dir = Join-Path $env:LOCALAPPDATA 'AlertasRivas'
$cfg = Get-Content (Join-Path $Dir 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$server = if ($cfg.server) { $cfg.server.TrimEnd('/') } else { 'https://ntfy.sh' }
$pruebas = @(
    @{ title = 'RIV-Alert AMARILLO · PRUEBA · Lluvia 15 mm en 1 h'; priority = 3; tags = @('yellow_circle', 'nivel-amarillo', 'evento-prueba'); message = 'Prueba de RIV-Alert AMARILLO (notificación). No es un aviso real.' },
    @{ title = 'RIV-Alert NARANJA · PRUEBA · Rachas 90 km/h'; priority = 4; tags = @('orange_circle', 'nivel-naranja', 'evento-prueba'); message = 'Prueba de RIV-Alert NARANJA (alerta media). No es un aviso real.' },
    @{ title = 'RIV-Alert ROJO · PRUEBA · Río Manzanares en Rivas'; priority = 5; tags = @('red_circle', 'nivel-rojo', 'evento-prueba'); message = 'Prueba de RIV-Alert ROJO (alerta máxima). No es un aviso real.' }
)
foreach ($p in $pruebas) {
    $p.topic = $cfg.topic
    $p.click = 'https://www.aemet.es/es/eltiempo/prediccion/avisos?k=mad'
    $body = [System.Text.Encoding]::UTF8.GetBytes(($p | ConvertTo-Json -Compress))
    Invoke-RestMethod -Uri $server -Method Post -Body $body -ContentType 'application/json; charset=utf-8' | Out-Null
    Start-Sleep -Seconds 3
}
Write-Host 'Enviadas 3 alertas de prueba.'

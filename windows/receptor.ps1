# Receptor de Alertas Rivas para Windows
# Escucha el canal de ntfy y muestra:
#   - MADRID   (prioridad 3): notificación normal
#   - CORREDOR (prioridad 4): notificación que se queda en pantalla hasta cerrarla
#   - RIVAS    (prioridad 5): ventana roja encima de todo con alarma que suena hasta pulsar ENTENDIDO

$ErrorActionPreference = 'Stop'
$Dir      = Join-Path $env:LOCALAPPDATA 'AlertasRivas'
$LastFile = Join-Path $Dir 'ultimo_id.txt'
$LogFile  = Join-Path $Dir 'receptor.log'

function Log([string]$t) {
    try {
        $line = "{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $t
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
        if ((Get-Item $LogFile).Length -gt 1MB) { Remove-Item $LogFile -Force }
    } catch {}
}

# Solo una copia funcionando a la vez
$creado = $false
$mutex = New-Object System.Threading.Mutex($true, 'Local\AlertasRivasReceptor', [ref]$creado)
if (-not $creado) { exit }

$cfg    = Get-Content (Join-Path $Dir 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$Topic  = $cfg.topic
$Server = if ($cfg.server) { $cfg.server.TrimEnd('/') } else { 'https://ntfy.sh' }

Add-Type -AssemblyName System.Windows.Forms, System.Drawing, System.Net.Http
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$AppId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'

function Esc([string]$s) { [System.Security.SecurityElement]::Escape($s) }

function Mostrar-Toast([string]$titulo, [string]$cuerpo, [int]$prioridad, [string]$url) {
    if ($prioridad -ge 4) {
        $escenario = 'scenario="reminder"'
        $audio = '<audio src="ms-winsoundevent:Notification.Reminder"/>'
    } else {
        $escenario = ''
        $audio = '<audio src="ms-winsoundevent:Notification.Default"/>'
    }
    $acciones = ''
    if ($url) {
        $acciones = '<actions><action content="Ver avisos" activationType="protocol" arguments="' + (Esc $url) + '"/>' +
                    '<action content="Cerrar" activationType="system" arguments="dismiss"/></actions>'
    } elseif ($escenario) {
        $acciones = '<actions><action content="Cerrar" activationType="system" arguments="dismiss"/></actions>'
    }
    $launch = if ($url) { 'activationType="protocol" launch="' + (Esc $url) + '"' } else { '' }
    $xml = "<toast $escenario $launch><visual><binding template=`"ToastGeneric`">" +
           "<text>$(Esc $titulo)</text><text>$(Esc $cuerpo)</text></binding></visual>$audio$acciones</toast>"
    $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
    $doc.LoadXml($xml)
    $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId).Show($toast)
}

function Mostrar-AlarmaRivas([string]$titulo, [string]$cuerpo, [string]$url) {
    $sonido = $null
    $wav = Join-Path $env:WINDIR 'Media\Alarm01.wav'
    try {
        if (Test-Path $wav) {
            $sonido = New-Object System.Media.SoundPlayer $wav
            $sonido.PlayLooping()
        }
    } catch { $sonido = $null }

    $f = New-Object System.Windows.Forms.Form
    $f.Text = 'ALERTA RIVAS'
    $f.TopMost = $true
    $f.StartPosition = 'CenterScreen'
    $f.Size = New-Object System.Drawing.Size(640, 400)
    $f.BackColor = [System.Drawing.Color]::FromArgb(176, 0, 32)
    $f.FormBorderStyle = 'FixedDialog'
    $f.MaximizeBox = $false
    $f.MinimizeBox = $false
    $f.ShowInTaskbar = $true

    $lt = New-Object System.Windows.Forms.Label
    $lt.Text = $titulo
    $lt.ForeColor = 'White'
    $lt.Font = New-Object System.Drawing.Font('Segoe UI', 17, [System.Drawing.FontStyle]::Bold)
    $lt.SetBounds(20, 15, 590, 90)
    $f.Controls.Add($lt)

    $lb = New-Object System.Windows.Forms.TextBox
    $lb.Multiline = $true
    $lb.ReadOnly = $true
    $lb.ScrollBars = 'Vertical'
    $lb.Text = ($cuerpo -replace "`r?`n", "`r`n")
    $lb.Font = New-Object System.Drawing.Font('Segoe UI', 11)
    $lb.SetBounds(20, 110, 590, 170)
    $f.Controls.Add($lb)

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = 'ENTENDIDO'
    $ok.Font = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
    $ok.BackColor = 'White'
    $ok.SetBounds(20, 295, 290, 50)
    $ok.Add_Click({ $f.Close() })
    $f.Controls.Add($ok)
    $f.AcceptButton = $ok

    if ($url) {
        $ver = New-Object System.Windows.Forms.Button
        $ver.Text = 'Ver avisos'
        $ver.Font = New-Object System.Drawing.Font('Segoe UI', 12)
        $ver.BackColor = 'White'
        $ver.SetBounds(320, 295, 290, 50)
        $ver.Add_Click({ Start-Process $url })
        $f.Controls.Add($ver)
    }

    # Parpadeo para llamar la atención
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 700
    $script:rojo = $true
    $timer.Add_Tick({
        $script:rojo = -not $script:rojo
        $f.BackColor = if ($script:rojo) { [System.Drawing.Color]::FromArgb(176, 0, 32) } else { [System.Drawing.Color]::FromArgb(240, 125, 0) }
    })
    $timer.Start()
    $f.Add_Shown({ $f.Activate() })
    [void]$f.ShowDialog()
    $timer.Stop()
    if ($sonido) { $sonido.Stop() }
    $f.Dispose()
}

function Procesar($m) {
    $titulo = if ($m.title) { [string]$m.title } else { 'Alerta' }
    $cuerpo = [string]$m.message
    $prio   = if ($m.priority) { [int]$m.priority } else { 3 }
    $url    = [string]$m.click
    # Si llega con retraso (el PC estaba apagado), no hacemos sonar la alarma
    $edad = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [int64]$m.time
    if ($edad -gt 3600) {
        $hora = [DateTimeOffset]::FromUnixTimeSeconds([int64]$m.time).LocalDateTime.ToString('dd/MM HH:mm')
        Mostrar-Toast "$titulo" "(Recibido con retraso, enviado el $hora)`n$cuerpo" ([Math]::Min($prio, 4)) $url
        return
    }
    if ($prio -ge 5) {
        try { Mostrar-Toast $titulo $cuerpo 4 $url } catch { Log "toast: $_" }
        Mostrar-AlarmaRivas $titulo $cuerpo $url
    } else {
        Mostrar-Toast $titulo $cuerpo $prio $url
    }
}

Log "Receptor iniciado. Canal: $Topic"
$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [System.Threading.Timeout]::InfiniteTimeSpan

while ($true) {
    try {
        $since = ''
        if (Test-Path $LastFile) { $since = (Get-Content $LastFile -Raw).Trim() }
        $url = "$Server/$Topic/json"
        if ($since) { $url += "?since=$since" }
        $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $url)
        $resp = $client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        [void]$resp.EnsureSuccessStatusCode()
        $stream = $resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
        Log 'Conectado a ntfy.'
        while ($null -ne ($line = $reader.ReadLine())) {
            if (-not $line.Trim()) { continue }
            $m = $line | ConvertFrom-Json
            if ($m.event -ne 'message') { continue }
            Set-Content -Path $LastFile -Value $m.id -Encoding ASCII
            try { Procesar $m } catch { Log "Error mostrando alerta: $_" }
        }
        Log 'Conexión cerrada por el servidor.'
    } catch {
        Log "Sin conexión ($($_.Exception.Message)). Reintento en 30 s."
    }
    Start-Sleep -Seconds 30
}

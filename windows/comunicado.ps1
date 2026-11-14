# RIV-Alert · Mandar un comunicado manual a todos los suscritos al canal (móviles y PCs).
# No necesita GitHub: publica directamente en el canal de ntfy guardado en config.json.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$Dir = Join-Path $env:LOCALAPPDATA 'AlertasRivas'
$cfg = Get-Content (Join-Path $Dir 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$server = if ($cfg.server) { $cfg.server.TrimEnd('/') } else { 'https://ntfy.sh' }

$f = New-Object System.Windows.Forms.Form
$f.Text = 'RIV-Alert · Mandar comunicado a todos'
$f.Size = New-Object System.Drawing.Size(560, 430)
$f.StartPosition = 'CenterScreen'
$f.FormBorderStyle = 'FixedDialog'
$f.MaximizeBox = $false
$f.BackColor = [System.Drawing.Color]::FromArgb(27, 58, 140)
$fuente = New-Object System.Drawing.Font('Segoe UI', 10)

$l1 = New-Object System.Windows.Forms.Label
$l1.Text = 'Mensaje (la primera línea será el título):'
$l1.ForeColor = 'White'; $l1.Font = $fuente
$l1.SetBounds(15, 12, 520, 22)
$f.Controls.Add($l1)

$txt = New-Object System.Windows.Forms.TextBox
$txt.Multiline = $true; $txt.ScrollBars = 'Vertical'; $txt.Font = $fuente
$txt.SetBounds(15, 38, 515, 220)
$f.Controls.Add($txt)

$l2 = New-Object System.Windows.Forms.Label
$l2.Text = 'Nivel:'; $l2.ForeColor = 'White'; $l2.Font = $fuente
$l2.SetBounds(15, 272, 60, 24)
$f.Controls.Add($l2)

$cb = New-Object System.Windows.Forms.ComboBox
$cb.DropDownStyle = 'DropDownList'; $cb.Font = $fuente
[void]$cb.Items.AddRange(@('Informativo', 'Amarillo (notificación)', 'Naranja (alerta media)', 'Rojo (alerta máxima)'))
$cb.SelectedIndex = 0
$cb.SetBounds(80, 270, 250, 28)
$f.Controls.Add($cb)

$btn = New-Object System.Windows.Forms.Button
$btn.Text = 'ENVIAR A TODOS'
$btn.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
$btn.BackColor = [System.Drawing.Color]::FromArgb(240, 125, 0)
$btn.SetBounds(15, 320, 515, 48)
$f.Controls.Add($btn)

$btn.Add_Click({
    $texto = $txt.Text.Trim()
    if (-not $texto) { [void][System.Windows.Forms.MessageBox]::Show('Escribe un mensaje.'); return }
    $niveles = @(@{ n = 'informativo'; p = 3; tag = 'loudspeaker'; t = '' },
                 @{ n = 'amarillo'; p = 3; tag = 'yellow_circle'; t = ' AMARILLO' },
                 @{ n = 'naranja'; p = 4; tag = 'orange_circle'; t = ' NARANJA' },
                 @{ n = 'rojo'; p = 5; tag = 'red_circle'; t = ' ROJO' })
    $nv = $niveles[$cb.SelectedIndex]
    $ok = [System.Windows.Forms.MessageBox]::Show("¿Enviar este comunicado$($nv.t) a todos los suscritos?", 'Confirmar', 'YesNo', 'Question')
    if ($ok -ne 'Yes') { return }
    $primera = ($texto -split "`r?`n")[0]
    if ($primera.Length -gt 80) { $primera = $primera.Substring(0, 80) }
    $ahora = Get-Date -Format 'dd/MM \a \l\a\s HH:mm'
    $msg = @{
        topic    = $cfg.topic
        title    = "RIV-Alert · COMUNICADO$($nv.t) · $primera"
        message  = "$texto`n`nComunicado manual enviado el $ahora desde RIV-Alert · Protección Civil Rivas (aviso interno, no oficial)."
        priority = $nv.p
        tags     = @($nv.tag, "nivel-$($nv.n)", 'evento-comunicado')
        click    = 'https://riv-alert.vercel.app/'
    }
    try {
        $body = [System.Text.Encoding]::UTF8.GetBytes(($msg | ConvertTo-Json -Compress))
        Invoke-RestMethod -Uri $server -Method Post -Body $body -ContentType 'application/json; charset=utf-8' | Out-Null
        [void][System.Windows.Forms.MessageBox]::Show('Comunicado enviado.', 'RIV-Alert')
        $f.Close()
    } catch {
        [void][System.Windows.Forms.MessageBox]::Show("No se pudo enviar: $($_.Exception.Message)", 'RIV-Alert', 'OK', 'Error')
    }
})
[void]$f.ShowDialog()

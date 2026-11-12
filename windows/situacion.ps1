# RIV-Alert · Ver la situación actual (último dato del vigilante) y pedir una comprobación nueva.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$Panel = 'https://guillemerinotes.github.io/alertas-rivas/'
$Actions = 'https://github.com/guillemerinotes/alertas-rivas/actions/workflows/vigilante.yml'
$NIV = @{ 'amarillo' = 1; 'naranja' = 2; 'rojo' = 3 }
$COL = @('normalidad', 'AMARILLO', 'NARANJA', 'ROJO')

try {
    $d = Invoke-RestMethod -Uri ($Panel + 'datos.json?t=' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()) -TimeoutSec 20
} catch {
    [void][System.Windows.Forms.MessageBox]::Show("No se pudieron descargar los datos: $($_.Exception.Message)", 'RIV-Alert', 'OK', 'Error')
    exit
}
$peor = 0
$l = New-Object System.Collections.Generic.List[string]
$act = ([DateTimeOffset]::Parse($d.actualizado)).LocalDateTime
$min = [int]((Get-Date) - $act).TotalMinutes
$l.Add("Datos de las $($act.ToString('HH:mm')) del $($act.ToString('dd/MM')) (hace $min min)")
$l.Add('')
$l.Add('AEMET (zona de Rivas):')
if (-not $d.avisos -or $d.avisos.Count -eq 0) { $l.Add('  · Sin avisos') }
foreach ($a in $d.avisos) {
    $n = $NIV[$a.nivel]; if ($n -gt $peor) { $peor = $n }
    $l.Add("  · $($a.nivel.ToUpper()) $($a.fenomeno) $($a.valor)")
}
$l.Add(''); $l.Add('Ríos (SAIH Tajo):')
foreach ($p in $d.rios.PSObject.Properties) {
    $r = $p.Value
    if (-not $r.tramo) { continue }
    if ($r.nivel -gt $peor) { $peor = $r.nivel }
    $donde = if ($r.tramo -eq 'rivas') { 'en Rivas' } else { 'aguas arriba' }
    $l.Add(("  · {0} ({1}): {2:N2} {3} · {4}" -f $r.desc, $donde, [double]$r.valor, $r.unidad, $COL[[int]$r.nivel]))
}
if ($d.incendios -and $d.incendios.hoy) {
    $l.Add(''); $l.Add("Incendios: riesgo hoy $($d.incendios.hoy), mañana $($d.incendios.manana)")
    if ($d.incendios.nivel -gt $peor) { $peor = $d.incendios.nivel }
}
if ($d.sismos -and $d.sismos.Count -gt 0) {
    $l.Add(''); $l.Add('Terremotos cercanos (10 días):')
    foreach ($s in $d.sismos) { $l.Add("  · M$($s.mag) a $([int]$s.dist) km · $($s.lugar)"); if ($s.nivel -gt $peor) { $peor = $s.nivel } }
}
if ($d.noticias -and $d.noticias.Count -gt 0) {
    $l.Add(''); $l.Add('Noticias (no oficiales):')
    foreach ($n in ($d.noticias | Select-Object -First 5)) { $l.Add("  · $($n.titulo) — Fuente: $($n.medio)") }
}

$f = New-Object System.Windows.Forms.Form
$f.Text = "RIV-Alert · Situación actual · peor nivel: $($COL[$peor])"
$f.Size = New-Object System.Drawing.Size(720, 560)
$f.StartPosition = 'CenterScreen'
$f.BackColor = @([System.Drawing.Color]::FromArgb(27, 58, 140), [System.Drawing.Color]::FromArgb(200, 160, 0),
                 [System.Drawing.Color]::FromArgb(240, 125, 0), [System.Drawing.Color]::FromArgb(176, 0, 32))[$peor]
$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true; $tb.ReadOnly = $true; $tb.ScrollBars = 'Vertical'
$tb.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$tb.Text = ($l -join "`r`n")
$tb.SetBounds(12, 12, 680, 420)
$f.Controls.Add($tb)

$b1 = New-Object System.Windows.Forms.Button
$b1.Text = 'Abrir panel'; $b1.BackColor = 'White'; $b1.SetBounds(12, 445, 220, 50)
$b1.Add_Click({ Start-Process $Panel })
$f.Controls.Add($b1)

$b2 = New-Object System.Windows.Forms.Button
$b2.Text = 'Pedir comprobación nueva (GitHub)'; $b2.BackColor = 'White'; $b2.SetBounds(242, 445, 270, 50)
$b2.Add_Click({
    [void][System.Windows.Forms.MessageBox]::Show("Se abrirá GitHub. Pulsa 'Run workflow', marca 'PEDIR ACTUALIZACIÓN' y vuelve a pulsar 'Run workflow'. En 1-2 minutos llega el resumen a todos.", 'RIV-Alert')
    Start-Process $Actions
})
$f.Controls.Add($b2)

$b3 = New-Object System.Windows.Forms.Button
$b3.Text = 'Cerrar'; $b3.BackColor = 'White'; $b3.SetBounds(522, 445, 170, 50)
$b3.Add_Click({ $f.Close() })
$f.Controls.Add($b3)
[void]$f.ShowDialog()

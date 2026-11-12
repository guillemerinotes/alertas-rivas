# RIV-Alert

Aviso interno (no oficial) de Protección Civil Rivas para emergencias que pueden afectar a **Rivas-Vaciamadrid**.
El nivel de RIV-Alert es el **color oficial** de cada fuente:

| Nivel | Móvil (ntfy) | Windows |
|---|---|---|
| 🟡 **AMARILLO** | Notificación (prioridad 3) | Notificación |
| 🟠 **NARANJA** | Alerta media (prioridad 4) | Ventana naranja + un aviso sonoro |
| 🔴 **ROJO** | Alerta máxima (prioridad 5) | Ventana roja + alarma continua hasta ENTENDIDO |

Fuentes vigiladas (cada 10 min, cron-job.org → GitHub Actions):

- **AEMET Meteoalerta**, solo la zona de Rivas (Metropolitana y Henares, 722802): lluvia 1 h / 12 h, viento,
  nieve, tormentas (incluye granizo), temperaturas, niebla, polvo. Colores oficiales de AEMET.
- **SAIH Tajo**: ríos en Rivas y aguas arriba con los umbrales oficiales de la CHT.
- **IGN**: terremotos. Sin colores oficiales: nivel por magnitud y distancia (criterio RIV-Alert, `monitor/sismos.py`).
- **AEMET riesgo de incendio forestal** en Rivas: alto = amarillo, muy alto = naranja, extremo = rojo
  (equivalencia de RIV-Alert, `monitor/incendios.py`).

## Ríos (SAIH Tajo)

Nivel de las estaciones de aforo de la Confederación Hidrográfica del Tajo con sus umbrales oficiales
(amarillo / naranja / rojo):

- **RIVAS**: Manzanares en Rivas-Vaciamadrid (AR18), Jarama en Mejorada–San Fernando (AR17), Jarama en San Fernando (MC02).
  Amarillo = notificación fija; naranja o rojo = alarma.
- **CORREDOR**: Jarama en Algete, Henares en Espinillo y Humanes, Jarama en Puente Titulcia.
- **MADRID**: Manzanares en Puente de San Fernando y Colmenar Viejo, Jarama en Valdepeñas, Tajuña en Armuña.

Avisa al cruzar un umbral, al bajar y al volver a normalidad (con 3 cm de margen para no repetir avisos).

## Cómo funciona

- `monitor/monitor.py` se ejecuta cada 10 minutos en GitHub Actions (`.github/workflows/vigilante.yml`).
  Descarga el estado completo de avisos de AEMET para Madrid (formato CAP, sin clave) y lo compara con
  `state.json`.
- Las notificaciones se envían al canal privado de [ntfy](https://ntfy.sh) guardado en el secreto `NTFY_TOPIC`.
- El móvil recibe con la app ntfy; el PC con `windows/receptor.ps1`.

## Secretos del repositorio (Settings → Secrets and variables → Actions)

| Nombre | Valor |
|---|---|
| `NTFY_TOPIC` | nombre del canal de ntfy (obligatorio) |
| `AEMET_API_KEY` | clave gratuita de AEMET OpenData (opcional; activa la confirmación en Rivas) |

## Windows

Descarga la carpeta `windows`, haz doble clic en `Instalar.bat` y pega el nombre del canal.
`Probar.bat` (en `%LOCALAPPDATA%\AlertasRivas`) envía 3 alertas de prueba. `desinstalar.ps1` lo quita todo.

## Prueba completa

Pestaña **Actions → Vigilante AEMET → Run workflow** marcando *Enviar 3 notificaciones de prueba*.

Datos: © AEMET. Este sistema es una ayuda personal y no sustituye a los canales oficiales (AEMET, 112, ES-Alert).

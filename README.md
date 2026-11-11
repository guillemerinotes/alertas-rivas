# Alertas Rivas

Sistema de alertas meteorológicas basado en los avisos oficiales de **AEMET** (Meteoalerta) para la
Comunidad de Madrid, con tres niveles:

| Nivel | Cuándo | Móvil (ntfy) | Windows |
|---|---|---|---|
| **MADRID** | Aviso amarillo o superior en *Sierra de Madrid* o *Sur, Vegas y Oeste* | prioridad normal | notificación normal |
| **CORREDOR** | Aviso en *Metropolitana y Henares* que la previsión de Rivas **no** confirma | prioridad alta | notificación fija hasta cerrarla |
| **RIVAS** | Aviso NARANJA o ROJO en *Metropolitana y Henares* (siempre), o AMARILLO confirmado con la previsión horaria de AEMET para Rivas (28123), o sin datos para comprobarlo | prioridad máxima | ventana roja con alarma hasta pulsar ENTENDIDO |

Avisa cuando un aviso **es nuevo** (hoy, mañana o pasado), **sube** o **baja** de nivel, **entra en vigor**,
se **cancela**, o cambia su confirmación en Rivas.

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

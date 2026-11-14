// RIV-Alert · Acciones de coordinador (Vercel Function).
// Variables de entorno (Vercel → Settings → Environment Variables):
//   COORD_PASSWORD  contraseña de coordinador
//   GITHUB_TOKEN    token fine-grained del repo alertas-rivas con Actions: Read and write y Contents: Read and write
//   NTFY_TOPIC      (opcional) canal personal, para recibir también los comunicados
//   PASS_JEFES      contraseña de miembros jefes (ven los enlaces de jefes y voluntarios)
//   PASS_VOLUNTARIOS contraseña de miembros voluntarios (ven solo el enlace de voluntarios)
//   CANAL_JEFES / CANAL_VOLUNTARIOS  nombres (secretos) de los canales ntfy de cada grupo
//   BLOB_READ_WRITE_TOKEN  almacén privado (Vercel Blob) para comunicados y respuestas
import crypto from "node:crypto";
import { put, get, list } from "@vercel/blob";

const APP = "https://riv-alert.vercel.app/";
const ESTADOS = { disponible: "Disponible", minutos: "Disponible en X min", no: "No disponible" };

// ---------- almacén privado ----------
async function guardar(ruta, datos) {
  await put(ruta, JSON.stringify(datos), { access: "private", addRandomSuffix: false, allowOverwrite: true, contentType: "application/json" });
}
async function leer(ruta) {
  const r = await get(ruta, { access: "private", useCache: false });
  if (!r || r.statusCode !== 200 || !r.stream) return null;
  return JSON.parse(await new Response(r.stream).text());
}
async function listar(prefijo) {
  const out = [];
  let cursor;
  do {
    const r = await list({ prefix: prefijo, cursor, limit: 1000 });
    out.push(...r.blobs);
    cursor = r.hasMore ? r.cursor : undefined;
  } while (cursor);
  return out;
}
const idValido = (id) => typeof id === "string" && /^[0-9]{13}-[a-f0-9]{8}$/.test(id);
const slug = (s) => String(s).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
async function respuestasDe(id) {
  const blobs = await listar(`respuestas/${id}/`);
  const rs = (await Promise.all(blobs.map((b) => leer(b.pathname).catch(() => null)))).filter(Boolean);
  return rs.sort((a, b) => a.ts.localeCompare(b.ts));
}

const REPO = "guillemerinotes/alertas-rivas";
const WORKFLOW = "vigilante.yml";
const GH = "https://api.github.com";
const PANEL = "https://guillemerinotes.github.io/alertas-rivas/";
const NIVELES = { informativo: 0, amarillo: 1, naranja: 2, rojo: 3 };
const PRIORIDAD = { 0: 3, 1: 3, 2: 4, 3: 5 };
const EMOJI = { 0: "loudspeaker", 1: "yellow_circle", 2: "orange_circle", 3: "red_circle" };
const NOMBRE = { 0: "info", 1: "amarillo", 2: "naranja", 3: "rojo" };

function igual(dada, real) {
  if (!real || typeof dada !== "string") return false;
  const a = crypto.createHash("sha256").update(dada).digest();
  const b = crypto.createHash("sha256").update(real).digest();
  return crypto.timingSafeEqual(a, b);
}

function claveOk(dada) {
  const real = process.env.COORD_PASSWORD || "";
  if (!real || typeof dada !== "string") return false;
  const a = crypto.createHash("sha256").update(dada).digest();
  const b = crypto.createHash("sha256").update(real).digest();
  return crypto.timingSafeEqual(a, b);
}

async function gh(path, opts = {}) {
  const r = await fetch(GH + path, {
    ...opts,
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "riv-alert-app",
      ...(opts.headers || {}),
    },
  });
  if (!r.ok && r.status !== 204) throw new Error(`GitHub ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.status === 204 ? null : r.json();
}

async function leerGrupo() {
  const f = await gh(`/repos/${REPO}/contents/grupo.json?ref=main`);
  return { cfg: JSON.parse(Buffer.from(f.content, "base64").toString("utf8")), sha: f.sha };
}

async function ntfy(topic, msg) {
  const r = await fetch("https://ntfy.sh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, ...msg }),
  });
  if (!r.ok) throw new Error(`ntfy ${r.status}`);
}

// Admite el formato antiguo de un solo grupo
function normalizar(d) {
  const grupos = d && d.grupos ? d.grupos : { voluntarios: { nombre: "Voluntarios", ...d } };
  // Los canales son secretos: vienen de CANAL_JEFES / CANAL_VOLUNTARIOS, no del repositorio
  for (const [k, g] of Object.entries(grupos)) {
    grupos[k] = { ...g, canal: process.env["CANAL_" + k.toUpperCase()] || g.canal || null };
  }
  return grupos;
}
const TIPOS = ["aemet", "rios", "embalses", "incendios", "sismos", "noticias", "fin", "resumen"];

const espera = (ms) => new Promise((r) => setTimeout(r, ms));

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "GET") {
    // Configuración pública del grupo (canal para suscribirse y qué recibe)
    try {
      const r = await fetch(`https://raw.githubusercontent.com/${REPO}/main/grupo.json?t=${Date.now()}`);
      const grupos = normalizar(await r.json());
      // Los canales no se publican: solo se ven entrando como miembro o coordinador
      const pub = Object.fromEntries(Object.entries(grupos).map(([k, g]) => [k, { ...g, canal: null }]));
      return res.status(200).json({ grupos: pub });
    } catch (e) {
      return res.status(500).json({ error: "No se pudo leer la configuración" });
    }
  }
  if (req.method !== "POST") return res.status(405).json({ error: "Método no permitido" });

  const body = typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};

  // Respuesta de disponibilidad a un comunicado (sin contraseña: el id del comunicado hace de llave)
  if (body.accion === "ver_comunicado" || body.accion === "responder") {
    if (!idValido(body.id)) return res.status(400).json({ error: "Comunicado no válido" });
    let c;
    try { c = await leer(`comunicados/${body.id}.json`); } catch (e) { c = null; }
    if (!c) return res.status(404).json({ error: "No encuentro ese comunicado" });
    if (body.accion === "ver_comunicado") {
      return res.status(200).json({ ok: true, comunicado: { ts: c.ts, texto: c.texto, nivel: c.nivel, destino: c.destino, firma: c.firma } });
    }
    const nombre = String(body.nombre || "").trim().replace(/\s+/g, " ").slice(0, 50);
    const estado = String(body.estado || "");
    if (nombre.length < 2) return res.status(400).json({ error: "Escribe tu nombre" });
    if (!ESTADOS[estado]) return res.status(400).json({ error: "Respuesta no válida" });
    const min = estado === "minutos" ? Math.max(1, Math.min(600, parseInt(body.min, 10) || 0)) : null;
    if (estado === "minutos" && !min) return res.status(400).json({ error: "Indica en cuántos minutos" });
    await guardar(`respuestas/${body.id}/${slug(nombre) || "anonimo"}.json`, { nombre, estado, min, ts: new Date().toISOString() });
    return res.status(200).json({ ok: true, mensaje: "Respuesta enviada. Gracias." });
  }

  // Acceso de miembros: devuelve solo los canales de su grupo
  if (body.accion === "miembro") {
    let grupo = null;
    if (igual(body.clave, process.env.PASS_JEFES)) grupo = "jefes";
    else if (igual(body.clave, process.env.PASS_VOLUNTARIOS)) grupo = "voluntarios";
    else if (claveOk(body.clave)) grupo = "coordinador";
    if (!grupo) {
      await espera(1500);
      return res.status(401).json({ error: "Contraseña incorrecta" });
    }
    try {
      const r = await fetch(`https://raw.githubusercontent.com/${REPO}/main/grupo.json?t=${Date.now()}`);
      const grupos = normalizar(await r.json());
      const ver = grupo === "voluntarios" ? ["voluntarios"] : ["jefes", "voluntarios"];
      const canales = ver.filter((k) => grupos[k]?.canal).map((k) => ({ grupo: k, nombre: grupos[k].nombre || k, canal: grupos[k].canal }));
      return res.status(200).json({ ok: true, grupo, canales });
    } catch (e) {
      return res.status(500).json({ error: "No se pudo leer la configuración" });
    }
  }
  if (!claveOk(body.clave)) {
    await espera(1500); // frena a quien pruebe contraseñas
    return res.status(401).json({ error: "Contraseña incorrecta" });
  }
  try {
    switch (body.accion) {
      case "login": {
        const { cfg } = await leerGrupo();
        return res.status(200).json({ ok: true, grupos: normalizar(cfg) });
      }

      case "actualizar": {
        await gh(`/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
          method: "POST",
          body: JSON.stringify({ ref: "main", inputs: { resumen: "true" } }),
        });
        return res.status(200).json({ ok: true, mensaje: "Comprobación lanzada. El resumen llegará en 1-2 minutos." });
      }

      case "comunicado": {
        const texto = String(body.texto || "").trim().slice(0, 3000);
        if (!texto) return res.status(400).json({ error: "El comunicado está vacío" });
        const n = NIVELES[body.nivel] ?? 0;
        const firma = String(body.firma || "").trim().slice(0, 60);
        const id = `${Date.now()}-${crypto.randomBytes(4).toString("hex")}`;
        const enlace = `${APP}?r=${id}`;
        const hora = new Date().toLocaleString("es-ES", { timeZone: "Europe/Madrid", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
        const primera = texto.split(/\r?\n/)[0].slice(0, 80);
        const msg = {
          title: `RIV-Alert · COMUNICADO${n ? " " + NOMBRE[n].toUpperCase() : ""} · ${primera}`,
          message: `${texto}\n\n${firma ? "Firma: " + firma + "\n" : ""}Comunicado manual (${hora}) · RIV-Alert · Protección Civil Rivas (aviso interno, no oficial).`,
          priority: PRIORIDAD[n],
          tags: [EMOJI[n], `nivel-${NOMBRE[n]}`, "evento-comunicado"],
          click: enlace,
          actions: [{ action: "view", label: "Responder (disponibilidad)", url: enlace, clear: false }],
        };
        const grupos = normalizar((await leerGrupo()).cfg);
        const para = body.destino === "jefes" || body.destino === "voluntarios" ? [body.destino] : Object.keys(grupos);
        const nombres = para.filter((k) => grupos[k]?.canal);
        if (!nombres.length) return res.status(400).json({ error: "Ese grupo no tiene canal" });
        const destinos = [...new Set([...nombres.map((k) => grupos[k].canal), process.env.NTFY_TOPIC].filter(Boolean))];
        const quien = nombres.map((k) => grupos[k].nombre || k).join(" y ");
        let guardado = true;
        try {
          await guardar(`comunicados/${id}.json`, { id, ts: new Date().toISOString(), texto, nivel: NOMBRE[n], destino: quien, firma });
        } catch (e) { guardado = false; }
        for (const t of destinos) await ntfy(t, msg);
        return res.status(200).json({ ok: true, id, mensaje: `Comunicado enviado a: ${quien}.` + (guardado ? "" : " (No se pudo guardar en el historial.)") });
      }

      case "historial": {
        const blobs = (await listar("comunicados/")).sort((a, b) => b.pathname.localeCompare(a.pathname)).slice(0, 30);
        const coms = (await Promise.all(blobs.map((b) => leer(b.pathname).catch(() => null)))).filter(Boolean);
        const conRespuestas = await Promise.all(coms.map(async (c) => ({ ...c, respuestas: await respuestasDe(c.id).catch(() => []) })));
        return res.status(200).json({ ok: true, comunicados: conRespuestas });
      }

      case "guardar_grupo": {
        const { cfg, sha } = await leerGrupo();
        const grupos = normalizar(cfg);
        const g = body.grupo;
        if (!grupos[g]) return res.status(400).json({ error: "Grupo desconocido" });
        grupos[g] = {
          ...grupos[g],
          niveles: (body.niveles || []).filter((x) => ["amarillo", "naranja", "rojo"].includes(x)),
          tipos: Object.fromEntries(TIPOS.map((k) => [k, !!(body.tipos || {})[k]])),
        };
        // No se guardan los canales en el repositorio
        const nuevo = { grupos: Object.fromEntries(Object.entries(grupos).map(([k, { canal, ...resto }]) => [k, resto])) };
        await gh(`/repos/${REPO}/contents/grupo.json`, {
          method: "PUT",
          body: JSON.stringify({
            message: `App RIV-Alert: cambiar lo que recibe ${grupos[g].nombre || g}`,
            content: Buffer.from(JSON.stringify(nuevo, null, 2) + "\n").toString("base64"),
            sha,
            branch: "main",
          }),
        });
        return res.status(200).json({ ok: true, mensaje: `Guardado (${grupos[g].nombre || g}). Se aplica desde la próxima comprobación.` });
      }

      default:
        return res.status(400).json({ error: "Acción desconocida" });
    }
  } catch (e) {
    return res.status(500).json({ error: String(e.message || e).slice(0, 300) });
  }
}

#!/usr/bin/env node
/**
 * generar_seo.js — Programmatic SEO para Andén.ar
 * Lee app/index.html con jsdom, extrae LINEAS_CONFIG vivo y genera
 * páginas estáticas /horarios/{linea}/{estacion}/ + hubs + índice
 * + sitemap.xml + robots.txt.
 *
 * Uso:  node generar_seo.js [ruta-al-index.html] [carpeta-salida]
 * Default: app/index.html  y  raíz del repo (.)
 */

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

// ── Config ──────────────────────────────────────────────
const BASE_URL = 'https://heywillia.github.io/Anden-ar'; // cambiar acá el día del dominio propio
const APP_URL = BASE_URL + '/app/';
const INPUT = process.argv[2] || path.join(__dirname, 'app', 'index.html');
const OUTROOT = process.argv[3] || __dirname;
const HOY = new Date().toISOString().slice(0, 10);

// ── 1. Cargar la app viva en jsdom ──────────────────────
function cargarApp() {
  let html = fs.readFileSync(INPUT, 'utf8');
  // Congelar getDay(): bs_gc.getData consulta new Date().getDay() internamente.
  // Si el workflow corriera un sábado, 'labsab' devolvería datos de sábado.
  // Fijamos "miércoles" para que la extracción sea determinística.
  html = html.replace(/<head>/i, '<head><script>Date.prototype.getDay = function(){ return 3; };</script>');
  // Exponer los const top-level (no están en window) con un script extra
  const expose = `<script>
    window.__SEO__ = {
      LINEAS_CONFIG: LINEAS_CONFIG,
      SAB_LINES: SAB_LINES,
      hIdxPara: hIdxPara,
      SUBTE_CFG: typeof SUBTE_CFG !== 'undefined' ? SUBTE_CFG : null,
    };
  </script>`;
  html = html.replace(/<\/body>/i, expose + '</body>');

  const vc = new VirtualConsole(); // silenciar ruido de la app
  vc.on('jsdomError', () => {});
  const dom = new JSDOM(html, {
    runScripts: 'dangerously',
    url: 'https://localhost/app/index.html',
    pretendToBeVisual: true,
    virtualConsole: vc,
  });
  const seo = dom.window.__SEO__;
  if (!seo || !seo.LINEAS_CONFIG) {
    throw new Error('No pude extraer LINEAS_CONFIG: el script de la app falló al inicializar.');
  }
  return { dom, seo };
}

// ── 2. Helpers ──────────────────────────────────────────
function slugify(s) {
  return s
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[ªº]/g, 'a')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
function limpiarNombre(n) {
  // saca emoji y espacios sobrantes
  return n.replace(/[\u{1F680}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, '').trim();
}
function fmt(t) {
  return String(t[0]).padStart(2, '0') + ':' + String(t[1]).padStart(2, '0');
}
function mins(t) { return t[0] * 60 + t[1]; }
function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// agrupa [[h,m],...] por hora → "05: 12 · 34 · 56"
function agruparPorHora(tiempos) {
  const porHora = new Map();
  for (const t of tiempos) {
    const h = String(t[0]).padStart(2, '0');
    if (!porHora.has(h)) porHora.set(h, []);
    porHora.get(h).push(String(t[1]).padStart(2, '0'));
  }
  return porHora;
}

// ── 3. Extracción de horarios por estación ──────────────
const TIPOS_DIA = { labsab: 'Lunes a viernes', sab: 'Sábados', domfer: 'Domingos y feriados' };

function tiposDiaDe(lineaKey, SAB_LINES) {
  return SAB_LINES.includes(lineaKey) ? ['labsab', 'sab', 'domfer'] : ['labsab', 'domfer'];
}

// devuelve array ordenado de [h,m] de salidas desde la estación idx
function salidasEstacion(cfg, lineaKey, tipoDia, dir, idx, totalEsts, hIdxPara) {
  let trenes;
  try { trenes = cfg.getData(tipoDia, dir) || []; } catch (e) { trenes = []; }
  const hi = hIdxPara(lineaKey, dir, idx, totalEsts);
  const out = [];
  for (const tren of trenes) {
    const t = tren.h[hi];
    if (t !== null && t !== undefined) out.push([t[0], t[1]]);
  }
  // orden cronológico tratando 00–03 como fin de servicio (después de las 23)
  out.sort((a, b) => {
    const ma = mins(a) < 180 ? mins(a) + 1440 : mins(a);
    const mb = mins(b) < 180 ? mins(b) + 1440 : mins(b);
    return ma - mb;
  });
  // dedup
  return out.filter((t, i) => i === 0 || mins(t) !== mins(out[i - 1]));
}

// ── 4. Plantillas HTML ──────────────────────────────────
const CSS = `*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d0f14;color:#f0f2f7;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;line-height:1.55;padding:20px 16px 48px;max-width:760px;margin:0 auto}
a{color:#e8c547;text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:1.5rem;margin:14px 0 8px;line-height:1.25}
h2{font-size:1.1rem;margin:26px 0 10px;color:#e8c547}
h3{font-size:.95rem;margin:18px 0 6px;color:#c9cedb}
p{margin:8px 0;color:#c9cedb}
.bc{font-size:.8rem;color:#8a91a3;margin-bottom:4px}.bc a{color:#8a91a3}
.linea-tag{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.75rem;font-weight:600;margin-bottom:6px}
.cta{display:block;text-align:center;background:#e8c547;color:#0d0f14;font-weight:700;padding:14px 18px;border-radius:12px;margin:22px 0;font-size:1rem}
.cta:hover{text-decoration:none;filter:brightness(1.08)}
table{width:100%;border-collapse:collapse;font-size:.88rem;margin:6px 0 14px}
td{padding:5px 8px;border-bottom:1px solid #1c2030;vertical-align:top}
td.h{color:#e8c547;font-weight:700;width:42px;font-variant-numeric:tabular-nums}
td.m{color:#f0f2f7;letter-spacing:.03em;font-variant-numeric:tabular-nums}
.freq{background:#141823;border:1px solid #1c2030;border-radius:10px;padding:12px 14px;margin:8px 0 14px;font-size:.9rem}
.freq b{color:#f0f2f7}
.noop{color:#8a91a3;font-style:italic;font-size:.88rem;margin:4px 0 14px}
ul.ests{list-style:none;columns:2;gap:18px;font-size:.88rem;margin:8px 0}
ul.ests li{margin:3px 0;break-inside:avoid}
footer{margin-top:34px;border-top:1px solid #1c2030;padding-top:14px;font-size:.78rem;color:#8a91a3}
.vig{font-size:.78rem;color:#8a91a3;margin-top:18px}`;

function paginaBase({ title, desc, canonical, breadcrumbHtml, breadcrumbLd, body }) {
  return `<!DOCTYPE html>
<html lang="es-AR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<meta name="description" content="${esc(desc)}">
<link rel="canonical" href="${canonical}">
<meta property="og:title" content="${esc(title)}">
<meta property="og:description" content="${esc(desc)}">
<meta property="og:url" content="${canonical}">
<meta property="og:type" content="website">
<style>${CSS}</style>
${breadcrumbLd ? `<script type="application/ld+json">${breadcrumbLd}</script>` : ''}
</head>
<body>
<nav class="bc">${breadcrumbHtml}</nav>
${body}
<footer>Andén.ar — horarios de trenes y subtes del AMBA, gratis y sin conexión. · <a href="${BASE_URL}/horarios/">Todas las líneas</a> · <a href="${APP_URL}">Abrir la app</a></footer>
</body>
</html>`;
}

function jsonLdBreadcrumb(items) {
  return JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((it, i) => ({
      '@type': 'ListItem', position: i + 1, name: it.name, item: it.url,
    })),
  });
}

// 4 plantillas de intro rotadas (anti contenido duplicado)
function intro(i, est, lineaNombre, esSubte, tIda, tVta) {
  const svc = esSubte ? 'del subte' : 'del tren';
  const tpl = [
    `Acá tenés todos los horarios ${svc} ${lineaNombre} en la estación ${est}, en ambas direcciones (hacia ${tIda} y hacia ${tVta}), actualizados según los cuadros oficiales vigentes.`,
    `¿A qué hora pasa el ${esSubte ? 'subte' : 'tren'} por ${est}? En esta página están las salidas ${esSubte ? 'de la' : 'de la línea'} ${lineaNombre} desde ${est} hacia ${tIda} y hacia ${tVta}, para días hábiles y fines de semana.`,
    `Consultá los horarios ${esSubte ? 'de la' : 'de la línea'} ${lineaNombre} en ${est}: salidas hacia ${tIda} y hacia ${tVta}, separadas por tipo de día, según la programación oficial del servicio.`,
    `Horarios completos ${svc} ${lineaNombre} desde la estación ${est}. Mirá las salidas en las dos direcciones (${tIda} / ${tVta}) y planificá tu viaje sin sorpresas.`,
  ];
  return tpl[i % tpl.length];
}

function tablaHoraria(tiempos) {
  if (!tiempos.length) return '<p class="noop">El servicio no opera este día en esta dirección.</p>';
  const porHora = agruparPorHora(tiempos);
  let rows = '';
  for (const [h, ms] of porHora) {
    rows += `<tr><td class="h">${h}</td><td class="m">${ms.join(' · ')}</td></tr>`;
  }
  return `<table>${rows}</table>`;
}

// ── 5. Página de estación ───────────────────────────────
function paginaEstacion(ctx) {
  const { lineaKey, cfg, nombreLimpio, nombreCorto, esSubte, ests, idx, est, lineaSlug, estSlug,
          tipos, hIdxPara, SUBTE_CFG, introIdx } = ctx;
  const url = `${BASE_URL}/horarios/${lineaSlug}/${estSlug}/`;
  const tipoSvc = esSubte ? 'subte' : 'tren';
  const title = `Horarios del ${tipoSvc} ${nombreCorto} en ${est} — Andén.ar`;
  const desc = `Horarios del ${tipoSvc} ${nombreCorto} en la estación ${est}: salidas hacia ${cfg.terminalIda} y hacia ${cfg.terminalVta}, días hábiles, sábados y domingos. Gratis y sin conexión con Andén.ar.`;

  let body = `<span class="linea-tag" style="background:${cfg.color}22;color:${cfg.color};border:1px solid ${cfg.color}55">${esc(nombreLimpio)}</span>
<h1>Horarios del ${tipoSvc} ${esc(nombreCorto)} en ${esc(est)}</h1>
<p>${esc(intro(introIdx, est, nombreCorto, esSubte, cfg.terminalIda, cfg.terminalVta))}</p>
<a class="cta" href="${APP_URL}">⚡ Ver el próximo ${tipoSvc} en tiempo real → Andén.ar</a>`;

  if (esSubte && SUBTE_CFG && SUBTE_CFG[lineaKey]) {
    // Subte: frecuencias + primer/último servicio en ESTA estación (modelo vivo)
    const labels = { lv: 'Lunes a viernes', sab: 'Sábados', df: 'Domingos y feriados' };
    for (const dir of ['haciafinal', 'haciaretiro']) {
      const term = dir === 'haciafinal' ? cfg.terminalIda : cfg.terminalVta;
      body += `<h2>Hacia ${esc(term)}</h2>`;
      for (const td of ['lv', 'sab', 'df']) {
        const tipoDia = td === 'lv' ? 'labsab' : td === 'sab' ? 'sab' : 'domfer';
        const freq = SUBTE_CFG[lineaKey][td][dir === 'haciafinal' ? 'ida' : 'vta'][4];
        const sal = salidasEstacion(cfg, lineaKey, tipoDia, dir, idx, ests.length, hIdxPara);
        if (!sal.length) { body += `<h3>${labels[td]}</h3><p class="noop">Sin servicio.</p>`; continue; }
        body += `<h3>${labels[td]}</h3>
<div class="freq">Primer servicio: <b>${fmt(sal[0])}</b> · Último: <b>${fmt(sal[sal.length - 1])}</b> · Frecuencia: <b>cada ${freq} min</b> aprox.</div>`;
      }
    }
  } else {
    // Tren: tablas de salidas por dirección y tipo de día
    // Detectar si labsab y domfer devuelven los mismos datos (línea "todos los días")
    const mismoTodosLosDias = !tipos.includes('sab') &&
      cfg.getData('labsab', 'haciafinal') === cfg.getData('domfer', 'haciafinal') &&
      cfg.getData('labsab', 'haciaretiro') === cfg.getData('domfer', 'haciaretiro');

    for (const dir of ['haciafinal', 'haciaretiro']) {
      const term = dir === 'haciafinal' ? cfg.terminalIda : cfg.terminalVta;
      body += `<h2>Hacia ${esc(term)}</h2>`;
      if (mismoTodosLosDias) {
        const sal = salidasEstacion(cfg, lineaKey, 'labsab', dir, idx, ests.length, hIdxPara);
        body += `<h3>Todos los días</h3>${tablaHoraria(sal)}`;
      } else {
        for (const tipoDia of tipos) {
          const sal = salidasEstacion(cfg, lineaKey, tipoDia, dir, idx, ests.length, hIdxPara);
          body += `<h3>${TIPOS_DIA[tipoDia]}</h3>${tablaHoraria(sal)}`;
        }
      }
    }
  }

  // Links internos: demás estaciones de la línea
  body += `<h2>Otras estaciones de la línea</h2><ul class="ests">`;
  for (let j = 0; j < ests.length; j++) {
    if (j === idx) continue;
    body += `<li><a href="${BASE_URL}/horarios/${lineaSlug}/${ctx.estSlugs[j]}/">${esc(ests[j])}</a></li>`;
  }
  body += `</ul>
<p><a href="${BASE_URL}/horarios/${lineaSlug}/">← Todas las estaciones de ${esc(nombreLimpio)}</a> · <a href="${BASE_URL}/horarios/">Todas las líneas</a></p>
<a class="cta" href="${APP_URL}">📲 Andén.ar: horarios offline, favoritos y alertas — gratis</a>
<p class="vig">${esSubte ? 'Frecuencias oficiales Emova.' : 'Horarios oficiales de Trenes Argentinos.'} Los horarios pueden sufrir modificaciones; ante dudas consultá la app o las fuentes oficiales. Última generación: ${HOY}.</p>`;

  const bcItems = [
    { name: 'Horarios', url: `${BASE_URL}/horarios/` },
    { name: nombreLimpio, url: `${BASE_URL}/horarios/${lineaSlug}/` },
    { name: est, url },
  ];
  const breadcrumbHtml = `<a href="${BASE_URL}/horarios/">Horarios</a> › <a href="${BASE_URL}/horarios/${lineaSlug}/">${esc(nombreLimpio)}</a> › ${esc(est)}`;
  return paginaBase({ title, desc, canonical: url, breadcrumbHtml, breadcrumbLd: jsonLdBreadcrumb(bcItems), body });
}

// ── 6. Hub de línea ─────────────────────────────────────
function paginaLinea(ctx) {
  const { cfg, nombreLimpio, nombreCorto, esSubte, ests, lineaSlug, estSlugs } = ctx;
  const url = `${BASE_URL}/horarios/${lineaSlug}/`;
  const tipoSvc = esSubte ? 'subte' : 'tren';
  const title = `Horarios del ${tipoSvc} ${nombreCorto} — todas las estaciones — Andén.ar`;
  const desc = `Horarios del ${tipoSvc} ${nombreCorto} (${cfg.terminalVta} ↔ ${cfg.terminalIda}): elegí tu estación y mirá todas las salidas por día y dirección. Gratis con Andén.ar.`;

  let body = `<span class="linea-tag" style="background:${cfg.color}22;color:${cfg.color};border:1px solid ${cfg.color}55">${esc(nombreLimpio)}</span>
<h1>Horarios del ${tipoSvc} ${esc(nombreCorto)}</h1>
<p>Recorrido: <b>${esc(cfg.terminalVta)} ↔ ${esc(cfg.terminalIda)}</b>. Elegí tu estación para ver todas las salidas, en ambas direcciones y por tipo de día.</p>
<a class="cta" href="${APP_URL}">⚡ Ver el próximo ${tipoSvc} en tiempo real → Andén.ar</a>
<h2>Estaciones</h2><ul class="ests">`;
  for (let j = 0; j < ests.length; j++) {
    body += `<li><a href="${url}${estSlugs[j]}/">${esc(ests[j])}</a></li>`;
  }
  body += `</ul>
<p><a href="${BASE_URL}/horarios/">← Todas las líneas</a></p>
<p class="vig">${esSubte ? 'Frecuencias oficiales Emova.' : 'Horarios oficiales de Trenes Argentinos.'} Pueden sufrir modificaciones. Última generación: ${HOY}.</p>`;

  const bcItems = [
    { name: 'Horarios', url: `${BASE_URL}/horarios/` },
    { name: nombreLimpio, url },
  ];
  const breadcrumbHtml = `<a href="${BASE_URL}/horarios/">Horarios</a> › ${esc(nombreLimpio)}`;
  return paginaBase({ title, desc, canonical: url, breadcrumbHtml, breadcrumbLd: jsonLdBreadcrumb(bcItems), body });
}

// ── 7. Índice general ───────────────────────────────────
function paginaIndice(lineas) {
  const url = `${BASE_URL}/horarios/`;
  const title = 'Horarios de trenes y subtes del AMBA — todas las líneas — Andén.ar';
  const desc = 'Horarios oficiales de todas las líneas de tren del AMBA (San Martín, Roca, Sarmiento, Mitre, Belgrano, Urquiza) y las 6 líneas de subte. Estación por estación, gratis.';
  const trenes = lineas.filter(l => !l.esSubte);
  const subtes = lineas.filter(l => l.esSubte);
  const item = l => `<li><a href="${BASE_URL}/horarios/${l.lineaSlug}/">${esc(l.nombreLimpio)}</a> <span style="color:#8a91a3">— ${esc(l.cfg.terminalVta)} ↔ ${esc(l.cfg.terminalIda)}</span></li>`;
  let body = `<h1>Horarios de trenes y subtes del AMBA</h1>
<p>Horarios oficiales, estación por estación, de todas las líneas de tren y subte de Buenos Aires y el conurbano. Elegí tu línea:</p>
<a class="cta" href="${APP_URL}">⚡ Ver el próximo tren en tiempo real → Andén.ar</a>
<h2>Trenes</h2><ul class="ests" style="columns:1">${trenes.map(item).join('')}</ul>
<h2>Subtes</h2><ul class="ests" style="columns:1">${subtes.map(item).join('')}</ul>
<p class="vig">Horarios oficiales de Trenes Argentinos y frecuencias oficiales Emova. Pueden sufrir modificaciones. Última generación: ${HOY}.</p>`;
  const breadcrumbHtml = `Horarios`;
  return paginaBase({ title, desc, canonical: url, breadcrumbHtml,
    breadcrumbLd: jsonLdBreadcrumb([{ name: 'Horarios', url }]), body });
}

// ── 8. Main ─────────────────────────────────────────────
function main() {
  const { dom, seo } = cargarApp();
  const { LINEAS_CONFIG, SAB_LINES, hIdxPara, SUBTE_CFG } = seo;

  const keys = Object.keys(LINEAS_CONFIG);
  console.log(`Líneas en LINEAS_CONFIG: ${keys.length}`);

  // construir metadata + slugs únicos de línea
  const lineas = [];
  const slugsLinea = new Map();
  for (const lineaKey of keys) {
    const cfg = LINEAS_CONFIG[lineaKey];
    const nombreLimpio = limpiarNombre(cfg.nombre);
    const esSubte = lineaKey.startsWith('subte_');
    const nombreCorto = esSubte ? nombreLimpio.replace(/^Subte\s+/i, '') : nombreLimpio;
    let lineaSlug = slugify(nombreLimpio);
    if (slugsLinea.has(lineaSlug)) lineaSlug = slugify(nombreLimpio + ' ' + lineaKey);
    if (slugsLinea.has(lineaSlug)) throw new Error(`Colisión irresoluble de slug de línea: ${lineaSlug}`);
    slugsLinea.set(lineaSlug, lineaKey);

    const ests = cfg.estaciones();
    if (!ests || !ests.length) throw new Error(`Línea ${lineaKey} sin estaciones`);

    // slugs de estación únicos dentro de la línea
    const estSlugs = [];
    const vistos = new Map();
    for (const e of ests) {
      let s = slugify(e);
      if (vistos.has(s)) s = s + '-' + (vistos.get(s) + 1);
      vistos.set(slugify(e), (vistos.get(slugify(e)) || 0) + 1);
      if (estSlugs.includes(s)) throw new Error(`Colisión de slug de estación en ${lineaKey}: ${s}`);
      estSlugs.push(s);
    }

    // verificar que la línea devuelve datos
    const prueba = cfg.getData('labsab', 'haciafinal');
    if (!prueba || !prueba.length) console.warn(`⚠ ${lineaKey}: getData('labsab','haciafinal') vacío`);

    lineas.push({ lineaKey, cfg, nombreLimpio, nombreCorto, esSubte, ests, estSlugs, lineaSlug,
                  tipos: tiposDiaDe(lineaKey, SAB_LINES) });
  }

  // generar archivos
  const urls = [];
  let totalPaginas = 0;
  let maxKB = 0, maxKBpage = '';
  const horariosDir = path.join(OUTROOT, 'horarios');
  fs.rmSync(horariosDir, { recursive: true, force: true });

  // índice
  fs.mkdirSync(horariosDir, { recursive: true });
  fs.writeFileSync(path.join(horariosDir, 'index.html'), paginaIndice(lineas));
  urls.push(`${BASE_URL}/horarios/`);
  totalPaginas++;

  let introIdx = 0;
  for (const L of lineas) {
    const dirLinea = path.join(horariosDir, L.lineaSlug);
    fs.mkdirSync(dirLinea, { recursive: true });
    fs.writeFileSync(path.join(dirLinea, 'index.html'), paginaLinea(L));
    urls.push(`${BASE_URL}/horarios/${L.lineaSlug}/`);
    totalPaginas++;

    for (let idx = 0; idx < L.ests.length; idx++) {
      const html = paginaEstacion({ ...L, idx, est: L.ests[idx], estSlug: L.estSlugs[idx],
                                    hIdxPara, SUBTE_CFG, introIdx: introIdx++ });
      const dirEst = path.join(dirLinea, L.estSlugs[idx]);
      fs.mkdirSync(dirEst, { recursive: true });
      fs.writeFileSync(path.join(dirEst, 'index.html'), html);
      const kb = Buffer.byteLength(html) / 1024;
      if (kb > maxKB) { maxKB = kb; maxKBpage = `${L.lineaSlug}/${L.estSlugs[idx]}`; }
      if (kb > 30) console.warn(`⚠ Página > 30KB: ${L.lineaSlug}/${L.estSlugs[idx]} (${kb.toFixed(1)}KB)`);
      urls.push(`${BASE_URL}/horarios/${L.lineaSlug}/${L.estSlugs[idx]}/`);
      totalPaginas++;
    }
  }

  // sitemap.xml (sin duplicados, URLs absolutas)
  const setUrls = new Set(urls);
  if (setUrls.size !== urls.length) throw new Error('URLs duplicadas en sitemap');
  const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls.map(u => `  <url><loc>${u}</loc><lastmod>${HOY}</lastmod></url>`).join('\n')}
  <url><loc>${BASE_URL}/</loc><lastmod>${HOY}</lastmod></url>
  <url><loc>${APP_URL}</loc><lastmod>${HOY}</lastmod></url>
</urlset>
`;
  fs.writeFileSync(path.join(OUTROOT, 'sitemap.xml'), sitemap);

  // robots.txt
  fs.writeFileSync(path.join(OUTROOT, 'robots.txt'),
`User-agent: *
Allow: /

Sitemap: ${BASE_URL}/sitemap.xml
`);

  console.log(`✔ ${totalPaginas} páginas generadas (${lineas.length} líneas)`);
  console.log(`✔ Página más pesada: ${maxKBpage} = ${maxKB.toFixed(1)}KB`);
  console.log(`✔ sitemap.xml con ${urls.length + 2} URLs`);
  dom.window.close();
  process.exit(0); // matar timers de la app
}

main();

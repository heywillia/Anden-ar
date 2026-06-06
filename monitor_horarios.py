"""
monitor_horarios.py — Andén.ar
Monitorea cambios en PDFs de horarios oficiales y manda email si hay novedades.
Corre via GitHub Actions cada lunes a las 11am hora Argentina.
"""

import hashlib, json, os, re, smtplib, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

HASH_FILE  = "hashes.json"
FROM_EMAIL = "info.anden.ar@gmail.com"
TO_EMAIL   = "info.anden.ar@gmail.com"
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AndenAr-Monitor/1.0)"}

# ─── Páginas a monitorear ────────────────────────────────────────────────────
# Todas las URLs fueron verificadas manualmente al 06/06/2026
PAGINAS = {
    # San Martín
    "sm":        ("San Martín – Retiro/Pilar/Cabred",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasanmartin/retiro-pilar-dr-cabred"),
    # Mitre
    "mitre_rt":  ("Mitre – Retiro/Tigre",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos-de-trenes/retiro-tigre"),
    "mitre_rjb": ("Mitre – Retiro/J.L.Suárez",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineamitre/retiro-jose-leon-suarez-bartolome-mitre"),
    "mitre_vz":  ("Mitre – Villa Ballester/Zárate",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineamitre/villa-ballester-zarate"),
    "mitre_vc":  ("Mitre – Victoria/Capilla del Señor",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineamitre/victoria-capilla-del-senor"),
    # Sarmiento
    "sm_om":     ("Sarmiento – Once/Moreno",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasarmiento/once-moreno"),
    "sm_mm":     ("Sarmiento – Moreno/Mercedes",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasarmiento/moreno-mercedes"),
    "sm_ml":     ("Sarmiento – Merlo/Lobos",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasarmiento/merlo-lobos"),
    # Roca — usan el patrón /horarios-tarifas-y-recorridos-de-trenes/
    "roca_lp":   ("Roca – La Plata",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos-de-trenes/plaza-constitucion-la-plata"),
    "roca_gk":   ("Roca – Glew/Alejandro Korn",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos-de-trenes/plaza-constitucion-glew-alejandro-korn"),
    "roca_ez":   ("Roca – Ezeiza/Cañuelas",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos-de-trenes/plaza-constitucion-ezeiza"),
    "roca_bq":   ("Roca – Bosques vía Quilmes",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos-de-trenes/plaza-constitucion-bosques-quilmes"),
    "roca_bt":   ("Roca – Bosques vía Temperley",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos-de-trenes/plaza-constitucion-bosques"),
    # Belgrano Norte — operado por Ferrovías, publicado en argentina.gob.ar
    "bn":        ("Belgrano Norte – Retiro/Villa Rosa",
                  "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos-de-trenes/retiro-villa-rosa"),
    # Urquiza — Metrovías
    "ur":        ("Urquiza – Lacroze/Gral. Lemos",
                  "https://www.metrovias.com.ar/linea-urquiza"),
    # Subte — Emova/Metrovías
    "subte":     ("Subte – Líneas A B C D E H",
                  "https://www.emova.com.ar/subte"),
}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()[:16]

def extraer_pdf_urls(html_bytes):
    """Extrae URLs de PDFs de horarios (excluye tarifas y otros)."""
    html = html_bytes.decode("utf-8", errors="replace")
    # Captura tanto href= como el patrón blank:# que usa argentina.gob.ar
    todas = re.findall(
        r'(?:href=["\']|blank:#)(https?://[^\s"\'<>]+\.pdf)',
        html, re.IGNORECASE
    )
    # Solo PDFs de horarios — excluir tarifas, mapas, institucionales
    horarios = []
    for u in todas:
        nombre = u.lower()
        if "tarifa" in nombre or "mapa" in nombre or "plano" in nombre:
            continue
        horarios.append(u)
    # Deduplicar preservando orden
    seen, result = set(), []
    for u in horarios:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result

def cargar_hashes():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE) as f:
            return json.load(f)
    return {}

def guardar_hashes(hashes):
    with open(HASH_FILE, "w") as f:
        json.dump(hashes, f, indent=2, ensure_ascii=False)

def enviar_email(cambios):
    if not GMAIL_PASS:
        print("⚠️  GMAIL_APP_PASSWORD no configurada — no se envía email.")
        return

    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    subject = f"🚆 Andén.ar — {len(cambios)} PDF(s) de horarios actualizados"

    filas_html, filas_txt = [], []
    for clave, nombre, pdf_url, tipo in cambios:
        emoji = "🆕" if tipo == "nuevo" else "🔄"
        filas_html.append(
            f'<li style="margin-bottom:12px"><b>{emoji} {nombre}</b><br>'
            f'<span style="color:#888;font-size:12px">{tipo.upper()}</span><br>'
            f'<a href="{pdf_url}" style="font-size:13px">{pdf_url}</a></li>'
        )
        filas_txt.append(f"  {emoji} {nombre}\n     {tipo.upper()}: {pdf_url}")

    html_body = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#e8c547;margin-bottom:4px">🚆 Andén.ar</h2>
      <p style="color:#888;margin-top:0">Monitor de horarios — {ahora}</p>
      <hr style="border:1px solid #333">
      <p>Se detectaron <b>{len(cambios)} cambio(s)</b> en PDFs oficiales:</p>
      <ul style="line-height:1.8;padding-left:20px">{''.join(filas_html)}</ul>
      <hr style="border:1px solid #333">
      <p style="color:#888;font-size:12px">
        Descargá los PDFs, verificá si los datos cambiaron y actualizá los arrays en el HTML.<br>
        Generado automáticamente por el monitor de Andén.ar.
      </p>
    </div>
    """
    txt_body = f"Andén.ar — Horarios actualizados ({ahora})\n\n" + "\n".join(filas_txt)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(txt_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(FROM_EMAIL, GMAIL_PASS)
        s.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
    print(f"✓ Email enviado a {TO_EMAIL}")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    hashes  = cargar_hashes()
    cambios = []
    errores = []

    for clave, (nombre, pagina_url) in PAGINAS.items():
        print(f"Revisando {nombre}...")
        try:
            html = fetch(pagina_url)
            pdf_urls = extraer_pdf_urls(html)

            if not pdf_urls:
                print(f"  ⚠️  Sin PDFs de horarios en la página")
                continue

            for pdf_url in pdf_urls:
                try:
                    pdf_data   = fetch(pdf_url)
                    nuevo_hash = hash_bytes(pdf_data)
                    hash_key   = f"{clave}::{pdf_url}"
                    viejo_hash = hashes.get(hash_key)

                    if viejo_hash is None:
                        cambios.append((clave, nombre, pdf_url, "nuevo"))
                        print(f"  🆕 NUEVO: {pdf_url[-70:]}")
                    elif viejo_hash != nuevo_hash:
                        cambios.append((clave, nombre, pdf_url, "actualizado"))
                        print(f"  🔄 ACTUALIZADO: {pdf_url[-70:]}")
                    else:
                        print(f"  ✓  Sin cambios")

                    hashes[hash_key] = nuevo_hash

                except Exception as e:
                    print(f"  ✗  Error descargando PDF: {e}")
                    errores.append(f"{nombre} — PDF: {e}")

        except Exception as e:
            print(f"  ✗  Error en página: {e}")
            errores.append(f"{nombre} — Página: {e}")

    guardar_hashes(hashes)

    print(f"\n{'='*50}")
    print(f"Resumen: {len(cambios)} cambios, {len(errores)} errores")

    if cambios:
        enviar_email(cambios)
    else:
        print("Sin cambios — no se envía email.")

    # Si más de la mitad de las páginas fallaron, marcar como error
    if len(errores) > len(PAGINAS) // 2:
        raise SystemExit(f"Demasiados errores ({len(errores)}/{len(PAGINAS)})")

if __name__ == "__main__":
    main()

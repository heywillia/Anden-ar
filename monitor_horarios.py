"""
monitor_horarios.py
Andén.ar — Monitoreo de cambios en PDFs de horarios oficiales.

Cómo funciona:
  1. Entra a la página oficial de cada línea
  2. Extrae las URLs de los PDFs de horarios que están publicados
  3. Compara contra los hashes guardados en hashes.json
  4. Si hay un PDF nuevo o distinto, manda un email con los detalles
  5. Guarda los nuevos hashes para la próxima corrida

Corre vía GitHub Actions una vez por semana (lunes 8am UTC-3).
"""

import hashlib
import json
import os
import re
import smtplib
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ─── Configuración ────────────────────────────────────────────
HASH_FILE   = "hashes.json"
FROM_EMAIL  = "info.anden.ar@gmail.com"
TO_EMAIL    = "info.anden.ar@gmail.com"
# La contraseña va como secret en GitHub Actions (GMAIL_APP_PASSWORD)
GMAIL_PASS  = os.environ.get("GMAIL_APP_PASSWORD", "")

# ─── Páginas a monitorear ─────────────────────────────────────
# Cada entrada: clave → (nombre legible, URL de la página)
PAGINAS = {
    "sm":       ("San Martín – Retiro/Pilar/Cabred",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasanmartin/retiro-pilar-dr-cabred"),
    "mitre_rt": ("Mitre – Retiro/Tigre",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineamitre/retiro-tigre"),
    "mitre_rjb":("Mitre – Retiro/J.L.Suárez",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineamitre/retiro-jose-leon-suarez-bartolome-mitre"),
    "mitre_vz": ("Mitre – Villa Ballester/Zárate",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineamitre/villa-ballester-zarate"),
    "mitre_vc": ("Mitre – Victoria/Capilla del Señor",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineamitre/victoria-capilla-del-senor"),
    "sm_om":    ("Sarmiento – Once/Moreno",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasarmiento/once-moreno"),
    "sm_mm":    ("Sarmiento – Moreno/Mercedes",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasarmiento/moreno-mercedes"),
    "sm_ml":    ("Sarmiento – Merlo/Lobos",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineasarmiento/merlo-lobos"),
    "roca_lp":  ("Roca – La Plata",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/linearoca/constitucion-la-plata"),
    "roca_gk":  ("Roca – Glew/Alejandro Korn",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/linearoca/constitucion-temperley-glew-alejandro-korn"),
    "roca_ez":  ("Roca – Ezeiza/Cañuelas",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/linearoca/constitucion-ezeiza-canuelas"),
    "roca_bq":  ("Roca – Bosques vía Quilmes",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/linearoca/constitucion-bosques-por-quilmes"),
    "roca_bt":  ("Roca – Bosques vía Temperley",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/linearoca/constitucion-bosques-por-temperley"),
    "bn":       ("Belgrano Norte – Retiro/Villa Rosa",
                 "https://www.argentina.gob.ar/transporte/trenes-argentinos/horarios-tarifas-y-recorridos/areametropolitana/lineabelgranonorte/retiro-villa-rosa"),
    "ur":       ("Urquiza – Federico Lacroze/Gral. Lemos",
                 "https://www.metrovias.com.ar/linea-urquiza/horarios"),
    "subte":    ("Subte – Líneas A B C D E H",
                 "https://www.emova.com.ar/subte/horarios"),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AndenAr-Monitor/1.0)"
}

# ─── Helpers ─────────────────────────────────────────────────

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()[:16]

def extraer_pdf_urls(html_bytes, base_url):
    """Extrae URLs de PDFs desde el HTML de la página."""
    html = html_bytes.decode("utf-8", errors="replace")
    # argentina.gob.ar usa: href="https://www.argentina.gob.ar/sites/default/files/xxx.pdf"
    # o el patrón blank:#https://...pdf
    urls = re.findall(
        r'(?:href=["\']|blank:#)(https?://[^\s"\'<>]+\.pdf)',
        html, re.IGNORECASE
    )
    # Filtrar solo los de horarios (descartar tarifas)
    urls = [u for u in urls if "horario" in u.lower() or "tren" in u.lower() or "diagram" in u.lower()]
    # Deduplicar preservando orden
    seen = set()
    result = []
    for u in urls:
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
        print("GMAIL_APP_PASSWORD no configurada — no se envía email.")
        return

    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    subject = f"🚆 Andén.ar — {len(cambios)} PDF(s) de horarios actualizados"

    lines_html = []
    lines_txt  = []
    for clave, nombre, pdf_url, tipo in cambios:
        emoji = "🆕" if tipo == "nuevo" else "🔄"
        lines_html.append(
            f"<li><b>{emoji} {nombre}</b><br>"
            f"<small>{tipo.upper()}</small> — "
            f'<a href="{pdf_url}">{pdf_url}</a></li>'
        )
        lines_txt.append(f"  {emoji} {nombre}\n     {tipo.upper()}: {pdf_url}")

    html_body = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#e8c547">🚆 Andén.ar — Horarios actualizados</h2>
      <p>El <b>{ahora}</b> se detectaron cambios en los PDFs oficiales:</p>
      <ul style="line-height:2">{''.join(lines_html)}</ul>
      <hr>
      <p style="color:#888;font-size:12px">
        Revisá los PDFs, actualizá los arrays en el HTML y commiteá una nueva versión.<br>
        Este email fue generado automáticamente por el monitor de Andén.ar.
      </p>
    </div>
    """
    txt_body = f"Andén.ar — Horarios actualizados ({ahora})\n\n" + "\n".join(lines_txt)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = FROM_EMAIL
    msg["To"]      = TO_EMAIL
    msg.attach(MIMEText(txt_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(FROM_EMAIL, GMAIL_PASS)
        s.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
    print(f"Email enviado a {TO_EMAIL}")

# ─── Main ─────────────────────────────────────────────────────

def main():
    hashes   = cargar_hashes()
    cambios  = []   # [(clave, nombre, pdf_url, tipo)]
    errores  = []

    for clave, (nombre, pagina_url) in PAGINAS.items():
        print(f"Revisando {nombre}...")
        try:
            html = fetch(pagina_url)
            pdf_urls = extraer_pdf_urls(html, pagina_url)

            if not pdf_urls:
                # Fallback: si no encontró PDFs con filtro, toma cualquier .pdf
                html_str = html.decode("utf-8", errors="replace")
                pdf_urls = list(dict.fromkeys(re.findall(
                    r'(?:href=["\']|blank:#)(https?://[^\s"\'<>]+\.pdf)',
                    html_str, re.IGNORECASE
                )))

            for pdf_url in pdf_urls:
                try:
                    pdf_data = fetch(pdf_url)
                    nuevo_hash = hash_bytes(pdf_data)
                    hash_key   = f"{clave}::{pdf_url}"
                    viejo_hash = hashes.get(hash_key)

                    if viejo_hash is None:
                        tipo = "nuevo"
                        cambios.append((clave, nombre, pdf_url, tipo))
                        print(f"  ⚠️  NUEVO PDF: {pdf_url}")
                    elif viejo_hash != nuevo_hash:
                        tipo = "actualizado"
                        cambios.append((clave, nombre, pdf_url, tipo))
                        print(f"  🔄 ACTUALIZADO: {pdf_url}")
                    else:
                        print(f"  ✓  Sin cambios: {pdf_url[-60:]}")

                    hashes[hash_key] = nuevo_hash

                except Exception as e:
                    print(f"  ✗  Error descargando {pdf_url}: {e}")
                    errores.append(f"{nombre}: {e}")

        except Exception as e:
            print(f"  ✗  Error en página {pagina_url}: {e}")
            errores.append(f"{nombre}: {e}")

    guardar_hashes(hashes)
    print(f"\nResumen: {len(cambios)} cambios, {len(errores)} errores.")

    if cambios:
        enviar_email(cambios)
    else:
        print("Sin cambios — no se envía email.")

    # Salir con error si hubo muchos errores (para que GitHub Actions lo marque)
    if len(errores) > len(PAGINAS) // 2:
        raise SystemExit(f"Demasiados errores ({len(errores)})")

if __name__ == "__main__":
    main()

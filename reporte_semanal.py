"""
reporte_semanal.py — Andén.ar
Junta métricas de GitHub Traffic + Google Search Console y manda un
reporte por email. Corre vía GitHub Actions los lunes a la mañana.

Filosofía: NO rastrea usuarios. Solo lee datos agregados que GitHub y
Google ya recolectan del lado del servidor. Nada se agrega a la app.

Secrets que usa (todos opcionales — si falta uno, esa sección se omite):
  GH_STATS_TOKEN   → fine-grained PAT con permiso Administration:read
  GMAIL_APP_PASSWORD → el mismo del monitor de horarios
  GSC_SA_JSON      → JSON de la cuenta de servicio de Search Console (opcional)
"""

import json, os, smtplib, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

REPO       = "heywillia/Anden-ar"
SITE_URL   = "https://heywillia.github.io/Anden-ar/"
FROM_EMAIL = "info.anden.ar@gmail.com"
TO_EMAIL   = "info.anden.ar@gmail.com"

GH_TOKEN   = os.environ.get("GH_STATS_TOKEN", "").strip()
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
GSC_SA_JSON = os.environ.get("GSC_SA_JSON", "").strip()

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ─── GitHub Traffic ──────────────────────────────────────────────────────────

def gh_get(path):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GH_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AndenAr-Reporte/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def metricas_github():
    """Devuelve dict con resumen de las últimas 2 semanas, o None si falla."""
    if not GH_TOKEN:
        print("Sin GH_STATS_TOKEN — omito sección GitHub.")
        return None
    try:
        views = gh_get("traffic/views")        # {count, uniques, views:[{timestamp,count,uniques}]}
        paths = gh_get("traffic/popular/paths") # [{path, title, count, uniques}]
    except Exception as e:
        print(f"GitHub Traffic error: {e}")
        return None

    dias = views.get("views", [])
    hoy = datetime.now(timezone.utc).date()
    hace7 = hoy - timedelta(days=7)
    hace14 = hoy - timedelta(days=14)

    sem_actual = {"v": 0, "u": 0, "por_dia": {}}
    sem_previa = {"v": 0, "u": 0}
    for d in dias:
        fecha = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).date()
        if fecha >= hace7:
            sem_actual["v"] += d["count"]
            sem_actual["u"] += d["uniques"]
            sem_actual["por_dia"][fecha] = d["count"]
        elif fecha >= hace14:
            sem_previa["v"] += d["count"]
            sem_previa["u"] += d["uniques"]

    # día más activo de la semana
    dia_top = None
    if sem_actual["por_dia"]:
        f, c = max(sem_actual["por_dia"].items(), key=lambda kv: kv[1])
        dia_top = (DIAS_ES[f.weekday()], c)

    # tendencia
    delta = None
    if sem_previa["v"] > 0:
        delta = round((sem_actual["v"] - sem_previa["v"]) / sem_previa["v"] * 100)

    # top páginas (limpiar el prefijo del repo para legibilidad)
    top = []
    for p in paths[:6]:
        ruta = p["path"].replace("/heywillia/Anden-ar", "") or "/"
        top.append((ruta, p["count"], p["uniques"]))

    return {
        "v": sem_actual["v"], "u": sem_actual["u"],
        "delta": delta, "dia_top": dia_top, "top_paths": top,
    }


# ─── Google Search Console (opcional, se enciende con la credencial) ──────────

def metricas_gsc():
    """Top búsquedas + clics de los últimos 7 días. None si no hay credencial."""
    if not GSC_SA_JSON:
        print("Sin GSC_SA_JSON — omito sección Search Console (todavía no configurada).")
        return None
    try:
        # Import perezoso: la lib solo hace falta si hay credencial
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(GSC_SA_JSON)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
        )
        service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

        hoy = datetime.now(timezone.utc).date()
        resp = service.searchanalytics().query(
            siteUrl=SITE_URL,
            body={
                "startDate": str(hoy - timedelta(days=7)),
                "endDate": str(hoy),
                "dimensions": ["query"],
                "rowLimit": 10,
            },
        ).execute()

        filas = []
        total_clicks = 0
        for row in resp.get("rows", []):
            q = row["keys"][0]
            clicks = int(row.get("clicks", 0))
            impr = int(row.get("impressions", 0))
            total_clicks += clicks
            filas.append((q, clicks, impr))
        return {"total_clicks": total_clicks, "queries": filas}
    except Exception as e:
        print(f"Search Console error: {e}")
        return None


# ─── Email ───────────────────────────────────────────────────────────────────

def construir_email(gh, gsc):
    ahora = datetime.now(timezone.utc) - timedelta(hours=3)  # ART
    rango = ahora.strftime("Semana al %d/%m/%Y")

    H = []  # bloques HTML
    T = []  # bloques texto plano

    if gh:
        flecha = ""
        if gh["delta"] is not None:
            signo = "▲" if gh["delta"] >= 0 else "▼"
            color = "#34d399" if gh["delta"] >= 0 else "#e55a5a"
            flecha = f'<span style="color:{color};font-weight:700"> {signo} {abs(gh["delta"])}%</span>'
        dia = f'{gh["dia_top"][0]} ({gh["dia_top"][1]} visitas)' if gh["dia_top"] else "—"
        filas_p = "".join(
            f'<tr><td style="padding:4px 8px;color:#c9cedb">{r}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#e8c547;font-weight:700">{c}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#8a91a3">{u} únicos</td></tr>'
            for r, c, u in gh["top_paths"]
        )
        H.append(f"""
        <h3 style="color:#e8c547;margin:24px 0 8px">📈 Visitas (GitHub Pages)</h3>
        <p style="margin:4px 0;font-size:15px"><b style="font-size:22px">{gh['v']}</b> visitas esta semana{flecha}<br>
           <span style="color:#8a91a3">{gh['u']} visitantes únicos</span></p>
        <p style="margin:8px 0;color:#c9cedb">Día más activo: <b>{dia}</b></p>
        <p style="margin:12px 0 4px;color:#c9cedb;font-weight:600">Páginas más vistas:</p>
        <table style="width:100%;border-collapse:collapse;font-size:13px">{filas_p}</table>
        """)
        T.append(f"VISITAS (GitHub Pages)\n  {gh['v']} visitas esta semana"
                 + (f" ({gh['delta']:+}% vs anterior)" if gh['delta'] is not None else "")
                 + f"\n  {gh['u']} únicos · Día top: {dia}")

    if gsc:
        filas_q = "".join(
            f'<tr><td style="padding:4px 8px;color:#c9cedb">{q}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#e8c547;font-weight:700">{c}</td>'
            f'<td style="padding:4px 8px;text-align:right;color:#8a91a3">{i} impr.</td></tr>'
            for q, c, i in gsc["queries"]
        )
        H.append(f"""
        <h3 style="color:#e8c547;margin:24px 0 8px">🔎 Búsquedas en Google</h3>
        <p style="margin:4px 0;font-size:15px"><b style="font-size:22px">{gsc['total_clicks']}</b> clics desde Google esta semana</p>
        <p style="margin:12px 0 4px;color:#c9cedb;font-weight:600">Qué buscó la gente:</p>
        <table style="width:100%;border-collapse:collapse;font-size:13px">{filas_q}</table>
        """)
        T.append("\nBÚSQUEDAS EN GOOGLE\n  " + f"{gsc['total_clicks']} clics\n  "
                 + "\n  ".join(f"{q} — {c} clics" for q, c, _ in gsc["queries"]))

    if not H:
        H.append('<p style="color:#c9cedb">No hubo datos disponibles esta semana. '
                 'Revisá que los secrets estén configurados.</p>')
        T.append("Sin datos disponibles esta semana.")

    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px;background:#0d0f14;color:#f0f2f7">
      <h2 style="color:#e8c547;margin-bottom:2px">🚆 Andén.ar — Reporte semanal</h2>
      <p style="color:#8a91a3;margin-top:0">{rango}</p>
      <hr style="border:0;border-top:1px solid #2a2f3f">
      {''.join(H)}
      <hr style="border:0;border-top:1px solid #2a2f3f;margin-top:24px">
      <p style="color:#8a91a3;font-size:11px">Datos agregados de GitHub y Google. La app no rastrea usuarios.</p>
    </div>
    """
    txt = f"Andén.ar — Reporte semanal ({rango})\n\n" + "\n".join(T)
    return html, txt


def enviar(html, txt):
    if not GMAIL_PASS:
        print("Sin GMAIL_APP_PASSWORD — imprimo en consola en vez de mandar.")
        print(txt)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🚆 Andén.ar — Reporte semanal"
    msg["From"] = FROM_EMAIL
    msg["To"] = TO_EMAIL
    msg.attach(MIMEText(txt, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(FROM_EMAIL, GMAIL_PASS)
        s.sendmail(FROM_EMAIL, TO_EMAIL, msg.as_string())
    print(f"✓ Reporte enviado a {TO_EMAIL}")


def main():
    gh = metricas_github()
    gsc = metricas_gsc()
    html, txt = construir_email(gh, gsc)
    enviar(html, txt)


if __name__ == "__main__":
    main()

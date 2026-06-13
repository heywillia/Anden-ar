"""
estado_servicio.py — Andén.ar
Consulta las alertas de servicio oficiales de API Transporte (GCBA)
para subtes y trenes, y genera estado.json en la raíz del repo.
Corre vía GitHub Actions cada 15 minutos.

Si las credenciales no están configuradas todavía, termina sin error
(la feature queda "dormida" hasta que existan los secrets).
"""

import json, os, sys, urllib.request, urllib.parse
from datetime import datetime, timezone

CLIENT_ID     = os.environ.get("APITRANSPORTE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("APITRANSPORTE_CLIENT_SECRET", "").strip()
SALIDA        = "estado.json"

BASE = "https://apitransporte.buenosaires.gob.ar"
# Endpoints de alertas de servicio (GTFS-Realtime en JSON).
# Se toleran 404/errores individuales: si un endpoint cambia, los demás siguen.
# El subte responde en /subtes/serviceAlerts (confirmado).
# Para trenes la ruta no es obvia: probamos candidatos y usamos el que dé 200.
ENDPOINTS_SUBTE = [f"{BASE}/subtes/serviceAlerts"]
ENDPOINTS_TREN_CANDIDATOS = [
    f"{BASE}/trenes/serviceAlerts",
    f"{BASE}/trenes/serviceAlert",
    f"{BASE}/trenes/alerts",
    f"{BASE}/trenes/forecastGTFS/serviceAlerts",
    f"{BASE}/transito/trenes/serviceAlerts",
]

# Normalización de nombres de línea para mostrar en la app
NOMBRES = {
    "lineaa": "Subte A", "lineab": "Subte B", "lineac": "Subte C",
    "linead": "Subte D", "lineae": "Subte E", "lineah": "Subte H",
    "premetro": "Premetro",
    "sanmartin": "San Martín", "mitre": "Mitre", "roca": "Roca",
    "sarmiento": "Sarmiento", "belgranonorte": "Belgrano Norte",
    "belgranosur": "Belgrano Sur", "urquiza": "Urquiza",
}

def nombre_linea(route_id, fallback=""):
    if not route_id:
        return fallback or "Servicio"
    clave = "".join(c for c in route_id.lower() if c.isalnum())
    for k, v in NOMBRES.items():
        if k in clave:
            return v
    return route_id or fallback or "Servicio"

def texto_es(translated):
    """Extrae el texto en español de un campo TranslatedString de GTFS-RT."""
    if not translated:
        return ""
    trs = translated.get("translation") or []
    # preferir es, si no el primero
    for t in trs:
        if (t.get("language") or "").lower().startswith("es"):
            return (t.get("text") or "").strip()
    return (trs[0].get("text") or "").strip() if trs else ""

# Enum GTFS-RT Alert.Effect (la API puede mandar número o texto)
EFFECT_ENUM = {
    1: "NO_SERVICE", 2: "REDUCED_SERVICE", 3: "SIGNIFICANT_DELAYS",
    4: "DETOUR", 5: "ADDITIONAL_SERVICE", 6: "MODIFIED_SERVICE",
    7: "OTHER_EFFECT", 8: "UNKNOWN_EFFECT", 9: "STOP_MOVED",
}
SEV_ALTA = {"NO_SERVICE", "REDUCED_SERVICE", "SIGNIFICANT_DELAYS", "STOP_MOVED"}

def _effect_str(alert):
    eff = alert.get("effect")
    if eff is None:
        return ""
    if isinstance(eff, int):
        return EFFECT_ENUM.get(eff, "")
    return str(eff).upper()

def severidad(alert):
    return "alta" if _effect_str(alert) in SEV_ALTA else "media"

def _url_con_creds(url):
    qs = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "json": 1,
    })
    return f"{url}?{qs}"

def fetch_json(url):
    req = urllib.request.Request(
        _url_con_creds(url),
        headers={"User-Agent": "AndenAr-Estado/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def parsear_alertas(tipo, data):
    entidades = data.get("entity") or data.get("Entity") or []
    alertas = []
    for ent in entidades:
        alert = ent.get("alert") or ent.get("Alert")
        if not alert:
            continue
        header = texto_es(alert.get("header_text") or alert.get("headerText"))
        desc   = texto_es(alert.get("description_text") or alert.get("descriptionText"))
        texto  = header or desc
        if desc and header and desc != header:
            # si la descripción agrega info, usarla acotada
            texto = header if len(desc) > 220 else desc
        if not texto:
            continue
        # línea afectada: primer informed_entity con route_id
        linea = ""
        for ie in (alert.get("informed_entity") or alert.get("informedEntity") or []):
            rid = ie.get("route_id") or ie.get("routeId") or ""
            if rid:
                linea = nombre_linea(rid)
                print(f"    [diag] route_id crudo: {rid!r} → {linea}")
                break
        if not linea:
            linea = "Subte" if tipo == "subte" else "Trenes"
        alertas.append({
            "linea": linea,
            "texto": texto[:240],
            "sev": severidad(alert),
        })
    return alertas

def consultar(tipo, urls):
    """Prueba los candidatos en orden; devuelve (alertas, ok). ok=False si todos fallan."""
    ultimo_err = None
    for url in urls:
        try:
            data = fetch_json(url)
            alertas = parsear_alertas(tipo, data)
            print(f"{tipo}: {len(alertas)} alerta(s) via {url.split(BASE)[-1]}" +
                  (" — servicio normal" if not alertas else ""))
            return alertas, True
        except Exception as e:
            ultimo_err = e
            print(f"{tipo}: probé {url.split(BASE)[-1]} → {e}")
    print(f"{tipo}: ningún endpoint respondió (último error: {ultimo_err})")
    return [], False

def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Credenciales de API Transporte no configuradas — feature dormida, salgo OK.")
        sys.exit(0)

    todas = []
    sub_alertas, sub_ok = consultar("subte", ENDPOINTS_SUBTE)
    todas.extend(sub_alertas)
    tren_alertas, tren_ok = consultar("tren", ENDPOINTS_TREN_CANDIDATOS)
    todas.extend(tren_alertas)

    if not sub_ok and not tren_ok:
        # Ambos modos fallaron: no pisar el estado anterior con datos vacíos.
        print("Ningún modo respondió; no se actualiza estado.json.")
        sys.exit(0)

    # dedup conservando orden (misma línea + mismo texto)
    vistos, dedup = set(), []
    for a in todas:
        k = (a["linea"], a["texto"])
        if k not in vistos:
            vistos.add(k)
            dedup.append(a)
    # alta severidad primero
    dedup.sort(key=lambda a: 0 if a["sev"] == "alta" else 1)

    nuevo = {
        "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
        "alertas": dedup[:8],
    }

    # Solo escribir si cambió el contenido (ignorando ts) para no spamear commits
    anterior = None
    if os.path.exists(SALIDA):
        try:
            anterior = json.load(open(SALIDA))
        except Exception:
            anterior = None
    if anterior and anterior.get("alertas") == nuevo["alertas"]:
        print("Sin cambios en alertas — no se reescribe estado.json.")
        sys.exit(0)

    with open(SALIDA, "w") as f:
        json.dump(nuevo, f, ensure_ascii=False, indent=1)
    print(f"estado.json actualizado: {len(nuevo['alertas'])} alerta(s).")

if __name__ == "__main__":
    main()

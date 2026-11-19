#!/usr/bin/env python3
"""Publicador de reels en Instagram (API con inicio de sesión de Instagram).

Lee agenda.json, publica lo que ya venció y deja el resultado en el mismo archivo.
No usa IA: lo ejecuta un programador gratuito (p. ej. GitHub Actions cada 15-30 min).

Secretos por variable de entorno (NUNCA en archivos):
  IG_TOKEN_<CUENTA>   token de la cuenta, p. ej. IG_TOKEN_LF_PRODUCCIONESS
Datos no secretos viven en config.json (id de cuenta de Instagram).

Uso:
  python publicar.py --dry-run        # muestra qué publicaría, sin llamar a la API
  python publicar.py                  # publica lo vencido
  python publicar.py --solo <id>      # fuerza un item concreto (p. ej. la prueba)
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone

API = "https://graph.instagram.com/v21.0"
AQUI = os.path.dirname(os.path.abspath(__file__))


def llamar(metodo, ruta, token, datos=None):
    url = f"{API}/{ruta}"
    if metodo == "GET":
        q = dict(datos or {}); q["access_token"] = token
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(q))
    else:
        cuerpo = dict(datos or {}); cuerpo["access_token"] = token
        req = urllib.request.Request(url, data=urllib.parse.urlencode(cuerpo).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} en {ruta}: {detalle[:400]}")  # nunca incluye el token


def publicar_reel(ig_id, token, item):
    datos = {
        "media_type": "REELS",
        "video_url": item["video_url"],
        "caption": item.get("caption", ""),
        "share_to_feed": "true",
    }
    if item.get("prueba"):
        # Reel de prueba: solo lo ven los que no te siguen. Verificar soporte con el primer reel.
        datos["trial_params"] = json.dumps({"graduation_strategy": "MANUAL"})
    cont = llamar("POST", f"{ig_id}/media", token, datos)["id"]

    for _ in range(40):  # hasta ~10 min procesando el video
        estado = llamar("GET", cont, token, {"fields": "status_code,status"})
        codigo = estado.get("status_code")
        if codigo == "FINISHED":
            break
        if codigo in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"El contenedor falló: {estado}")
        time.sleep(15)
    else:
        raise RuntimeError("Tiempo agotado esperando que Instagram procese el video")

    return llamar("POST", f"{ig_id}/media_publish", token, {"creation_id": cont})["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--solo")
    ap.add_argument("--agenda", default=os.path.join(AQUI, "agenda.json"))
    ap.add_argument("--config", default=os.path.join(AQUI, "config.json"))
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    agenda = json.load(open(a.agenda, encoding="utf-8"))
    ahora = datetime.now(timezone.utc)
    hubo_error = False

    for item in agenda:
        if a.solo and item["id"] != a.solo:
            continue
        if item.get("estado") != "pendiente":
            continue
        vence = datetime.fromisoformat(item["fecha_utc"].replace("Z", "+00:00"))
        if vence > ahora and not a.solo:
            continue

        cuenta = item["cuenta"]
        ig_id = cfg["cuentas"][cuenta]["ig_user_id"]
        var = "IG_TOKEN_" + cuenta.upper().replace(".", "_")
        token = os.environ.get(var)

        if a.dry_run:
            print(f"[dry-run] {item['id']} → @{cuenta} ({'prueba' if item.get('prueba') else 'normal'}) {item['video_url']}")
            continue
        if not token:
            print(f"Falta la variable {var}; se omite {item['id']}", file=sys.stderr)
            hubo_error = True
            continue

        try:
            item["media_id"] = publicar_reel(ig_id, token, item)
            item["estado"] = "publicado"
            item["publicado_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(f"Publicado {item['id']} → {item['media_id']}")
        except Exception as e:  # noqa: BLE001
            item["estado"] = "error"
            item["error"] = str(e)[:400]
            hubo_error = True
            print(f"ERROR en {item['id']}: {e}", file=sys.stderr)

    if not a.dry_run:
        json.dump(agenda, open(a.agenda, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    sys.exit(1 if hubo_error else 0)


if __name__ == "__main__":
    main()

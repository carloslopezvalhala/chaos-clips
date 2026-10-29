"""Panel web local: python ui.py  ->  http://127.0.0.1:8765"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from clipper import access, campaigns
from clipper.common import QUEUE, READY, ROOT, live_pid, load_config
from clipper.generator import PROJECTS
from clipper.templates import HOOK_STYLES, LAYOUTS, PRESETS, SUB_STYLES

DISCARDED = ROOT / "descartados"
LOGS = ROOT / "logs"
DISCARDED.mkdir(exist_ok=True)
LOGS.mkdir(exist_ok=True)
FOLDERS = {"cola": QUEUE, "listos": READY, "descartados": DISCARDED}
EDITABLE_CONFIG = ["stream_url", "publish_every_minutes", "clips_per_segment", "layout", "hook_seconds",
                   "clip_min_seconds", "clip_max_seconds", "max_clip_age_hours", "hashtags",
                   "live_profile", "live_template", "live_language", "live_campaign", "jumpcut", "bleep"]

app = Flask(__name__, static_folder=None)
app.json.sort_keys = False  # keep template presets in their intended order
access.setup(app)
tunnel = {"proc": None, "url": None}
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
jobs = {}  # "directo" | "tarea" -> {"proc", "log", "label", "started"}
lock = threading.Lock()


def start_job(kind, args, label):
    with lock:
        job = jobs.get(kind)
        if job and job["proc"].poll() is None:
            return False
        log_path = LOGS / f"{kind}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen([sys.executable, "-W", "ignore", "run.py", *args], cwd=ROOT, env=env,
                                stdout=log_file, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        jobs[kind] = {"proc": proc, "log": log_path, "label": label, "started": time.time()}
        return True


def stop_job(kind):
    pids = []
    job = jobs.get(kind)
    if job and job["proc"].poll() is None:
        pids.append(job["proc"].pid)
    if kind == "directo" and (pid := live_pid()):
        pids.append(pid)  # also a live job left running by an earlier panel
    for pid in set(pids):
        # /T also kills the ffmpeg recorder started by the job.
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


# ffmpeg chatter that looks scary but is harmless: HLS network hiccups it retries, and decoder
# warnings from seeking into a recording.
NOISE = ("tls @", "https @", "hls @", "Error in the pull", "IO error", "decode_slice", "Missing reference",
         "Invalid NAL", "missing picture", "Error splitting", "HF_TOKEN", "unauthenticated requests")


def is_noise(line):
    return any(n in line for n in NOISE)


def job_status(kind):
    job = jobs.get(kind)
    if not job:
        if kind == "directo" and live_pid():
            log_path = LOGS / "directo.log"
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines() if log_path.exists() else []
            return {"running": True, "label": "Directo",
                    "log": "\n".join(l for l in lines if not is_noise(l))[-6000:]}
        return {"running": False, "label": None, "log": ""}
    lines = [l for l in job["log"].read_text(encoding="utf-8", errors="replace").splitlines() if not is_noise(l)]
    return {"running": job["proc"].poll() is None, "label": job["label"], "started": job["started"],
            "log": "\n".join(lines[-80:])}


def clip_info(folder, d):
    meta_path = d / "meta.json"
    if not (d / "clip.mp4").exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["folder"] = folder
    meta["dir"] = d.name
    meta["video"] = f"/video/{folder}/{d.name}?v={int((d / 'clip.mp4').stat().st_mtime)}"
    meta["duration"] = round(meta["end"] - meta["start"], 1)
    return meta


def clip_dir(folder, name):
    base = FOLDERS.get(folder)
    if not base or "/" in name or "\\" in name or name.startswith("."):
        abort(404)
    d = base / name
    if not d.is_dir():
        abort(404)
    return d


from clipper.publish import post_text  # noqa: E402


@app.get("/")
def index():
    return send_from_directory(ROOT / "panel", "index.html")


@app.get("/api/status")
def status():
    return jsonify({
        "directo": job_status("directo"), "tarea": job_status("tarea"), "generador": job_status("generador"),
        "api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "counts": {k: sum(1 for _ in v.glob("*/meta.json")) for k, v in FOLDERS.items()},
    })


@app.get("/api/clips/<folder>")
def clips(folder):
    base = FOLDERS.get(folder) or abort(404)
    items = [c for d in base.iterdir() if d.is_dir() and (c := clip_info(folder, d))]
    key = (lambda c: c["rank"]) if folder == "cola" else (lambda c: (c["dir"]))
    return jsonify(sorted(items, key=key, reverse=True))


@app.get("/video/<folder>/<name>")
def video(folder, name):
    return send_file(clip_dir(folder, name) / "clip.mp4", mimetype="video/mp4", conditional=True)


@app.post("/api/clip/<folder>/<name>/<action>")
def clip_action(folder, name, action):
    d = clip_dir(folder, name)
    cfg = load_config()
    if action == "listo":
        dest = READY / f"{time.strftime('%m%d_%H%M')}_{name}"
        shutil.move(str(d), str(dest))
        meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
        (dest / "texto_post.txt").write_text(post_text(cfg, meta), encoding="utf-8")
    elif action == "descartar":
        shutil.move(str(d), str(DISCARDED / name))
    elif action == "recuperar":
        shutil.move(str(d), str(QUEUE / name))
    elif action == "carpeta":
        os.startfile(d)
    elif action == "editar":
        data = request.get_json()
        meta_path = d / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        hook_changed = data["hook"].strip() != meta["hook"]
        meta["hook"], meta["caption"] = data["hook"].strip(), data["caption"].strip()
        meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        if (d / "texto_post.txt").exists():
            (d / "texto_post.txt").write_text(post_text(cfg, meta), encoding="utf-8")
        if hook_changed and not start_job("tarea", ["rehacer", str(d)], f"Rehaciendo {name}"):
            return jsonify({"ok": False, "error": "Ya hay una tarea en marcha; espera a que termine."})
    else:
        abort(404)
    return jsonify({"ok": True})


@app.post("/api/directo/<action>")
def directo(action):
    if action == "iniciar":
        data = request.get_json(silent=True) or {}
        url = (data.get("url") or "").strip()
        if url:
            if not url.startswith(("http://", "https://")):
                return jsonify({"ok": False, "error": "Pega la URL completa del directo (https://…)."})
            cfg = load_config()
            cfg["stream_url"] = url
            cfg["live_profile"] = data.get("perfil", "generico")
            cfg["live_template"] = data.get("plantilla", "viral")
            cfg["live_language"] = data.get("idioma", "")
            cfg["live_campaign"] = data.get("campana") or None
            (ROOT / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        ok = start_job("directo", ["directo"], "Directo")
        return jsonify({"ok": ok, "error": None if ok else "Ya está en marcha."})
    stop_job("directo")
    return jsonify({"ok": True})


@app.post("/api/tarea")
def tarea():
    data = request.get_json()
    kind = data.get("tipo")
    if kind == "vod":
        args = ["vod", data["url"].strip()]
        if data.get("desde"):
            args += ["--desde", data["desde"].strip()]
        if data.get("hasta"):
            args += ["--hasta", data["hasta"].strip()]
        label = "Procesando VOD"
    elif kind == "video":
        path = data["ruta"].strip().strip('"')
        if not Path(path).is_file():
            return jsonify({"ok": False, "error": "No encuentro ese archivo."})
        args, label = ["video", path], f"Procesando {Path(path).name}"
    elif kind == "siguiente":
        args, label = ["publicar"], "Moviendo el mejor clip a listos"
    elif kind == "parar":
        stop_job("tarea")
        return jsonify({"ok": True})
    else:
        abort(400)
    ok = start_job("tarea", args, label)
    return jsonify({"ok": ok, "error": None if ok else "Ya hay una tarea en marcha."})


# ---------- Acceso desde el móvil (contraseña + túnel de Cloudflare) ----------

CLOUDFLARED = shutil.which("cloudflared") or r"C:\Program Files (x86)\cloudflared\cloudflared.exe"


def local_only():
    if not access.is_local():
        abort(403)


@app.get("/login")
def login_page():
    return send_from_directory(ROOT / "panel", "login.html")


@app.get("/manifest.json")
def manifest():
    return jsonify({"name": "Chaos Clips", "short_name": "Clips", "start_url": "/", "display": "standalone",
                    "background_color": "#0c0c0e", "theme_color": "#0c0c0e"})


@app.post("/api/login")
def api_login():
    return access.login()


@app.post("/api/logout")
def api_logout():
    from flask import session
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/movil")
def movil_status():
    running = tunnel["proc"] is not None and tunnel["proc"].poll() is None
    return jsonify({"local": access.is_local(), "password": access.password_set(),
                    "running": running, "url": tunnel["url"] if running else None})


@app.post("/api/movil/password")
def movil_password():
    local_only()
    pw = (request.get_json() or {}).get("password", "")
    if len(pw) < 8:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 8 caracteres."})
    access.set_password(pw)
    return jsonify({"ok": True})


def _read_tunnel_url(proc):
    import re
    for line in proc.stderr:
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
        if m and not tunnel["url"]:
            tunnel["url"] = m.group(0)
            print(f"\nAcceso desde el móvil: {tunnel['url']}\n", flush=True)


@app.post("/api/movil/<action>")
def movil(action):
    local_only()
    if action == "iniciar":
        if not access.password_set():
            return jsonify({"ok": False, "error": "Primero crea una contraseña."})
        if tunnel["proc"] and tunnel["proc"].poll() is None:
            return jsonify({"ok": True})
        if not Path(CLOUDFLARED).exists():
            return jsonify({"ok": False, "error": "No encuentro cloudflared. Instálalo con: winget install Cloudflare.cloudflared"})
        tunnel["url"] = None
        tunnel["proc"] = subprocess.Popen(
            [CLOUDFLARED, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=_read_tunnel_url, args=(tunnel["proc"],), daemon=True).start()
    elif action == "parar":
        if tunnel["proc"] and tunnel["proc"].poll() is None:
            tunnel["proc"].terminate()
        tunnel["url"] = None
    else:
        abort(404)
    return jsonify({"ok": True})


@app.get("/api/movil/qr.svg")
def movil_qr():
    local_only()
    if not tunnel["url"]:
        abort(404)
    import io
    import qrcode
    import qrcode.image.svg
    buf = io.BytesIO()
    qrcode.make(tunnel["url"], image_factory=qrcode.image.svg.SvgPathFillImage, box_size=12, border=2).save(buf)
    return app.response_class(buf.getvalue(), mimetype="image/svg+xml")


# ---------- Generador (YouTube URL -> clips) ----------

def project_dir(pid, cid=None):
    for part in (pid, cid):
        if part is not None and (not part or "/" in part or "\\" in part or part.startswith(".")):
            abort(404)
    d = PROJECTS / pid if cid is None else PROJECTS / pid / "clips" / cid
    if not d.is_dir():
        abort(404)
    return d


@app.get("/generador")
def generador_page():
    return send_from_directory(ROOT / "panel", "generador.html")


@app.get("/api/plantillas")
def plantillas():
    return jsonify({"presets": PRESETS, "layouts": LAYOUTS, "subs": SUB_STYLES, "hooks": HOOK_STYLES})


@app.get("/api/campanas")
def get_campanas():
    return jsonify(campaigns.load())


@app.post("/api/campanas")
def set_campanas():
    import re
    items, seen = [], set()
    for c in request.get_json() or []:
        name = (c.get("name") or "").strip()
        creator = (c.get("creator") or "").strip()
        if not name or not creator:
            continue
        key = c.get("key") or re.sub(r"[^a-z0-9]+", "", name.lower()) or "campana"
        while key in seen:
            key += "2"
        seen.add(key)
        tags = c.get("hashtags") or []
        tags = tags.split() if isinstance(tags, str) else tags
        items.append({"key": key, "name": name, "creator": creator,
                      "hashtags": [t if t.startswith("#") else f"#{t}" for t in tags if t.strip("#")],
                      "template": c.get("template") if c.get("template") in PRESETS else "viral",
                      "notes": (c.get("notes") or "").strip()})
    campaigns.save(items)
    return jsonify({"ok": True, "items": items})


@app.get("/api/proyectos")
def proyectos():
    items = []
    for p in PROJECTS.glob("*/project.json"):
        meta = json.loads(p.read_text(encoding="utf-8"))
        meta["n_made"] = sum(1 for _ in (p.parent / "clips").glob("*/meta.json"))
        items.append(meta)
    return jsonify(sorted(items, key=lambda m: m["created"], reverse=True))


@app.get("/api/proyecto/<pid>")
def proyecto(pid):
    d = project_dir(pid)
    meta = json.loads((d / "project.json").read_text(encoding="utf-8"))
    clips = []
    for m in (d / "clips").glob("*/meta.json"):
        if not (m.parent / "clip.mp4").exists():
            continue
        c = json.loads(m.read_text(encoding="utf-8"))
        c.pop("words", None)
        c["video"] = f"/pvideo/{pid}/{c['id']}?v={int((m.parent / 'clip.mp4').stat().st_mtime)}"
        c["duration"] = round(c["end"] - c["start"], 1)
        clips.append(c)
    meta["clips"] = sorted(clips, key=lambda c: c["viral"], reverse=True)
    return jsonify(meta)


@app.get("/pvideo/<pid>/<cid>")
def pvideo(pid, cid):
    path = project_dir(pid, cid) / "clip.mp4"
    if request.args.get("dl"):
        return send_file(path, mimetype="video/mp4", as_attachment=True, download_name=f"{pid}_{cid}.mp4")
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.post("/api/generar")
def generar():
    data = request.get_json()
    url = (data.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "Pega un enlace de YouTube válido."})
    args = ["generar", url, "--clips", str(int(data.get("clips", 10))), "--plantilla", data.get("plantilla", "viral"),
            "--min", str(int(data.get("min", 20))), "--max", str(int(data.get("max", 55)))]
    for key, flag in (("desde", "--desde"), ("hasta", "--hasta"), ("idioma", "--idioma")):
        if (data.get(key) or "").strip():
            args += [flag, data[key].strip()]
    if not data.get("censura", True):
        args.append("--sin-censura")
    if data.get("campana"):
        args += ["--campana", data["campana"]]
    if not data.get("cortes", True):
        args.append("--sin-cortes")
    if not data.get("pitido", True):
        args.append("--sin-pitido")
    ok = start_job("generador", args, "Generando clips")
    return jsonify({"ok": ok, "error": None if ok else "Ya se está generando otro vídeo; espera a que termine."})


@app.post("/api/generar/parar")
def generar_parar():
    stop_job("generador")
    return jsonify({"ok": True})


@app.post("/api/proyecto/<pid>/<cid>/<action>")
def proyecto_clip(pid, cid, action):
    d = project_dir(pid, cid)
    data = request.get_json(silent=True) or {}
    if action == "editar":
        meta_path = d / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        hook_changed = data["hook"].strip() != meta["hook"]
        meta["hook"], meta["caption"] = data["hook"].strip(), data["caption"].strip()
        meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        if hook_changed and not start_job("tarea", ["regenerar", str(d)], f"Rehaciendo clip {cid}"):
            return jsonify({"ok": False, "error": "Hay otra tarea en marcha; espera a que termine."})
    elif action == "plantilla":
        if not start_job("tarea", ["regenerar", str(d), "--plantilla", data["spec"]], f"Cambiando plantilla de {cid}"):
            return jsonify({"ok": False, "error": "Hay otra tarea en marcha; espera a que termine."})
    elif action == "descartar":
        dest = PROJECTS / pid / "descartados"
        dest.mkdir(exist_ok=True)
        shutil.move(str(d), str(dest / cid))
    elif action == "carpeta":
        os.startfile(d)
    else:
        abort(404)
    return jsonify({"ok": True})


@app.get("/api/config")
def get_config():
    cfg = load_config()
    defaults = {"live_profile": "generico", "live_template": "viral", "live_language": "", "live_campaign": ""}
    return jsonify({k: cfg.get(k, defaults.get(k)) for k in EDITABLE_CONFIG})


@app.post("/api/config")
def set_config():
    cfg = load_config()
    data = request.get_json()
    for k in EDITABLE_CONFIG:
        if k in data:
            v = data[k]
            if k not in cfg or isinstance(cfg[k], bool):
                v = bool(v) if isinstance(cfg.get(k), bool) else v
            elif isinstance(cfg[k], int) and not isinstance(cfg[k], bool):
                v = int(v)
            elif isinstance(cfg[k], list) and isinstance(v, str):
                v = v.split()
            cfg[k] = v
    (ROOT / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = PORT
    url = f"http://127.0.0.1:{port}"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Panel en {url} (cierra esta ventana para apagarlo)")
    try:
        app.run(host="127.0.0.1", port=port, threaded=True)
    finally:
        for k in list(jobs):
            if k != "directo":  # the live job keeps running; a new panel can still stop it
                stop_job(k)
        if tunnel["proc"] and tunnel["proc"].poll() is None:
            tunnel["proc"].terminate()

import json
import shutil
import subprocess
import time

from .common import QUEUE, READY, load_state, log, save_state


def queued_clips(cfg):
    clips = []
    for meta_path in QUEUE.glob("*/meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if time.time() - meta["created"] > cfg["max_clip_age_hours"] * 3600:
            continue  # stale: the moment isn't news anymore
        clips.append(meta)
    return sorted(clips, key=lambda m: m["rank"], reverse=True)


def post_text(cfg, meta):
    return f"{meta['caption']}\n\n{' '.join(meta.get('hashtags') or cfg['hashtags'])}"


def release_best(cfg):
    clips = queued_clips(cfg)
    if not clips:
        return None
    best = clips[0]
    dest = READY / f"{time.strftime('%m%d_%H%M')}_{best['id']}"
    shutil.move(str(QUEUE / best["id"]), str(dest))
    text = post_text(cfg, best)
    (dest / "texto_post.txt").write_text(text, encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value $input"], input=text,
                   text=True, capture_output=True)
    try:
        import winsound
        winsound.MessageBeep()
    except Exception:
        pass
    state = load_state()
    state["published"].append(best["id"])
    save_state(state)
    log("publicar", f"NUEVO CLIP PARA SUBIR -> {dest}")
    log("publicar", f"Hook: «{best['hook']}» | descripción copiada al portapapeles")
    return dest


def publish_forever(cfg, stop):
    every = cfg["publish_every_minutes"] * 60
    last = 0.0
    while not stop.is_set():
        if time.time() - last >= every and release_best(cfg):
            last = time.time()
        stop.wait(20)

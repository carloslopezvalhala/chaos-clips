import json
import shutil
import time
from pathlib import Path

from . import campaigns
from .common import QUEUE, SEGMENTS, load_state, log, probe_duration, save_state
from .detect import analyze
from .hooks import hashtags, make_hook
from .render import render_clip
from .templates import parse, spec_of
from .text import censor, profanity_count


def favorited(cfg):
    return cfg.get("live_profile", "generico") == "favorited"


def live_settings(cfg):
    """Effective settings for the live job. The Favorited profile keeps its English-only model;
    any other stream gets the multilingual model and the chosen template."""
    if favorited(cfg):
        return {**cfg, "language": "en"}
    return {**cfg, "whisper_model": cfg.get("generator_whisper_model", "small"),
            # Talk-heavy streams (podcasts, news, just chatting) have few loud spikes, so a lower bar.
            "language": cfg.get("live_language") or None, "min_brightness": 15, "min_score": 0.8}


def live_template(cfg):
    return None if favorited(cfg) else parse(cfg.get("live_template", "viral"))


def clip_texts(cfg, transcript):
    """(hook, caption, quality, hashtags) for a live clip, depending on the profile."""
    if favorited(cfg):
        hook, caption, quality = make_hook(cfg, transcript)
        return hook, caption, quality, hashtags(cfg)
    from .generator import generic_hook
    camp = campaigns.get(cfg.get("live_campaign"))
    hook, caption, quality = generic_hook(cfg, transcript, cfg.get("stream_title", ""), camp["creator"] if camp else None)
    caption, tags = campaigns.apply(camp, censor(caption), cfg.get("live_hashtags") or ["#shorts", "#stream", "#clips"])
    return censor(hook), caption, quality, tags


def process_window(cfg, src, t0, duration, label):
    """Finds the best moments in src[t0:t0+duration] and renders each one into cola/<id>/."""
    log("procesar", f"Analizando {label}…")
    cfg = live_settings(cfg)
    tpl = live_template(cfg)
    _, sentences, words, moments = analyze(cfg, src, t0, duration)
    log("procesar", f"{len(moments)} momento(s) candidato(s) en {label}")
    made = 0
    for m in moments:
        start, end = t0 + m["start"], t0 + m["end"]
        transcript = " ".join(s["text"] for s in sentences if s["end"] > m["start"] and s["start"] < m["end"])
        hook, caption, quality, tags = clip_texts(cfg, transcript)
        clip_id = f"{label}_{int(m['peak']):04d}"
        out = QUEUE / clip_id
        out.mkdir(parents=True, exist_ok=True)
        abs_words = [{**w, "start": w["start"] + t0, "end": w["end"] + t0} for w in words]
        layout = render_clip(src, start, end, abs_words, hook, out, cfg, tpl)
        if not layout:
            shutil.rmtree(out, ignore_errors=True)  # only holds this attempt's subs.ass
            continue
        swears = profanity_count(transcript)
        meta = {
            "id": clip_id, "created": time.time(), "source": str(src), "start": round(start, 2),
            "end": round(end, 2), "audio_score": round(m["score"], 2), "quality": quality,
            # Swear-heavy clips risk age restriction even when censored on screen, so they rank lower.
            "rank": round(m["score"] + 0.5 * quality - min(3.0, 0.8 * swears), 2), "swears": swears,
            "layout": layout, "hook": hook, "caption": caption, "hashtags": tags,
            "transcript": transcript, "template": spec_of(tpl) if tpl else None,
            "campaign": None if favorited(cfg) else cfg.get("live_campaign"),
        }
        (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        log("procesar", f"Clip listo en cola: {clip_id} (nota {meta['rank']}, diseño {layout}) «{hook}»")
        made += 1
    return made


def rerender(cfg, clip_dir, new_hook=False):
    """Re-renders an existing clip folder (same source and cut) with the current render code.
    With new_hook, also rewrites hook/caption/hashtags and recomputes the rank."""
    meta = json.loads((clip_dir / "meta.json").read_text(encoding="utf-8"))
    if not Path(meta["source"]).exists():
        log("rehacer", f"{clip_dir.name}: la grabación original ya se borró; no se puede rehacer")
        return False
    cfg = live_settings(cfg)
    if new_hook:
        meta["hook"], meta["caption"], meta["quality"], meta["hashtags"] = clip_texts(cfg, meta["transcript"])
        meta["swears"] = profanity_count(meta["transcript"])
        meta["rank"] = round(meta["audio_score"] + 0.5 * meta["quality"] - min(3.0, 0.8 * meta["swears"]), 2)
        (clip_dir / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    from .common import read_audio
    from .detect import transcribe
    start, end = meta["start"], meta["end"]
    _, words = transcribe(cfg, read_audio(meta["source"], start, end - start))
    words = [{**w, "start": w["start"] + start, "end": w["end"] + start} for w in words]
    tpl = parse(meta["template"]) if meta.get("template") else None
    layout = render_clip(meta["source"], start, end, words, meta["hook"], clip_dir, cfg, tpl)
    log("rehacer", f"{clip_dir.name}: {'OK, diseño ' + layout if layout else 'falló'}")
    return bool(layout)


def process_file(cfg, path, window_minutes=10):
    """VOD / local video mode: walks the whole file in windows."""
    total = probe_duration(path)
    win = window_minutes * 60
    t = 0.0
    while t < total - 5:
        process_window(cfg, path, t, min(win, total - t), f"{path.stem}_{int(t // 60):03d}m")
        t += win


def process_segments_forever(cfg, stop):
    """Live mode: processes each finished segment written by the recorder."""
    state = load_state()
    while not stop.is_set():
        segs = sorted(SEGMENTS.glob("*.ts"))
        # The newest segment is still being written unless it hasn't changed for a while.
        finished = [s for s in segs[:-1]] + [s for s in segs[-1:] if time.time() - s.stat().st_mtime > 90]
        todo = [s for s in finished if s.name not in state["processed"]]
        if not todo:
            stop.wait(15)
            continue
        seg = todo[0]
        try:
            process_window(cfg, seg, 0, probe_duration(seg), seg.stem)
        except Exception as e:
            log("procesar", f"Error con {seg.name}: {e}")
        state = load_state()  # make_hook() also writes the state file; don't clobber it
        state["processed"].append(seg.name)
        save_state(state)
        # Raw segments take ~1.8 GB/hour; drop processed ones once they're too old to clip from.
        for old in SEGMENTS.glob("*.ts"):
            if old.name in state["processed"] and time.time() - old.stat().st_mtime > cfg["keep_segments_hours"] * 3600:
                old.unlink(missing_ok=True)

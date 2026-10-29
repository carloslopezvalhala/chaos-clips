"""YouTube URL -> many ranked vertical clips with captions, saved under proyectos/<id>/."""
import json
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import campaigns
from .common import ROOT, log, probe_duration
from .detect import analyze
from .render import render_clip
from .templates import parse, spec_of
from .text import censor, profanity_count

PROJECTS = ROOT / "proyectos"
PROJECTS.mkdir(exist_ok=True)

SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "On-screen hook, max 9 words, same language as the transcript"},
        "caption": {"type": "string", "description": "Post caption, 1-2 short sentences, same language as the transcript"},
        "quality": {"type": "integer", "description": "1-10: how likely this clip is to go viral as a standalone short"},
    },
    "required": ["hook", "caption", "quality"],
    "additionalProperties": False,
}


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def set_status(project, **fields):
    meta = json.loads((project / "project.json").read_text(encoding="utf-8"))
    meta.update(fields)
    write_json(project / "project.json", meta)


def download(url, project, desde=None, hasta=None):
    cmd = ["yt-dlp", "--encoding", "utf-8", "--js-runtimes", "node", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
           "--merge-output-format", "mp4", "-o", str(project / "source.%(ext)s"), "--no-playlist",
           "--print", "after_move:filepath"]
    if desde or hasta:
        cmd += ["--download-sections", f"*{desde or '0'}-{hasta or 'inf'}"]
    else:
        # Cut out sponsor reads (community SponsorBlock data): ads are loud and fast, so they'd rank high.
        cmd += ["--sponsorblock-remove", "sponsor,selfpromo,interaction"]
    res = subprocess.run(cmd + [url], capture_output=True, text=True, encoding="utf-8", errors="replace")
    files = [l.strip() for l in res.stdout.splitlines() if l.strip()]
    if res.returncode != 0 or not files:
        raise RuntimeError(f"No se pudo descargar el vídeo: {res.stderr[-600:]}")
    return Path(files[-1])


def video_info(url):
    res = subprocess.run(["yt-dlp", "--encoding", "utf-8", "--js-runtimes", "node", "--no-playlist", "--skip-download",
                          "--print", "%(id)s\t%(title)s\t%(duration)s", url], capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = next((l for l in res.stdout.splitlines() if "\t" in l), None)
    if not line:
        raise RuntimeError(f"No encuentro ese vídeo: {res.stderr[-400:]}")
    vid, title, dur = line.split("\t", 2)
    return vid, title, float(dur) if dur not in ("NA", "None", "") else 0.0


def generic_hook(cfg, transcript, title, creator=None):
    """(hook, caption, quality). Claude when ANTHROPIC_API_KEY is set, otherwise the punchiest quote."""
    about = f"The clip features {creator}; mention {creator} by name in the caption.\n" if creator else ""
    if os.environ.get("ANTHROPIC_API_KEY") and transcript.strip():
        try:
            import anthropic
            resp = anthropic.Anthropic().beta.messages.create(
                model=cfg["claude_model"], max_tokens=2000,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": (
                    f'You turn moments from the video "{title}" into viral vertical shorts.\n{about}\n'
                    f"Transcript of this clip (auto-generated):\n<transcript>\n{transcript}\n</transcript>\n\n"
                    "Write, in the same language as the transcript:\n"
                    "- hook: on-screen text for the first seconds, max 9 words, curiosity or shock, lowercase. "
                    "Only describe what is actually said or happens; never invent. No emojis, hashtags or swear words.\n"
                    "- caption: 1-2 short sentences for the post description, specific to this clip.\n"
                    "- quality: honest 1-10 rating of how well this clip works on its own as a short "
                    "(needs a clear payoff, emotion or a strong statement; filler or missing context = 1-3).")}],
            )
            if resp.stop_reason != "refusal":
                data = json.loads(next(b.text for b in resp.content if b.type == "text"))
                return data["hook"].strip(), data["caption"].strip(), int(data["quality"])
        except Exception as e:
            log("hook", f"Claude falló ({type(e).__name__}: {e}); uso una frase del clip")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", transcript) if s.strip()]
    good = [s for s in sentences if 4 <= len(s.split()) <= 12] or sentences or [title]
    clean_lines = [s for s in good if not profanity_count(s)]
    good = clean_lines or good  # a swear-word hook is generic and risks age restriction
    best = max(good, key=lambda s: (s.endswith(("!", "?")), -abs(len(s.split()) - 7)))
    words = best.rstrip(".").split()
    hook = " ".join(words[:10]).lower()
    # The clip's own line, not the video title: identical descriptions on every post read as spam.
    caption = best[0].upper() + best[1:] if best else title
    return f"“{hook}”", caption, 5


def generate(cfg, url, n_clips=10, tpl_spec="viral", desde=None, hasta=None, language=None,
             min_s=20, max_s=55, censor_on=True, campaign_key=None, jumpcut=True, bleep=True):
    camp = campaigns.get(campaign_key)
    vid, title, _ = video_info(url)
    tag = f"_{(desde or '0').replace(':', '')}-{(hasta or 'fin').replace(':', '')}" if (desde or hasta) else ""
    project = PROJECTS / f"{vid}{tag}"
    (project / "clips").mkdir(parents=True, exist_ok=True)
    tpl = parse(tpl_spec)
    write_json(project / "project.json", {
        "id": project.name, "url": url, "title": title, "created": time.time(), "template": spec_of(tpl),
        "n_clips": n_clips, "censor": censor_on, "jumpcut": jumpcut, "bleep": bleep, "campaign": camp["key"] if camp else None,
        "status": "Descargando el vídeo…", "done": False,
    })
    log("generar", f"«{title}»")

    try:
        src = next(project.glob("source.*"), None) or download(url, project, desde, hasta)
        total = probe_duration(src)
        cfg = {**cfg, "whisper_model": cfg.get("generator_whisper_model", "small"), "language": language,
               "clip_min_seconds": min_s, "clip_max_seconds": max_s, "pre_peak_seconds": max_s * 0.55,
               "post_peak_seconds": max_s * 0.3, "min_brightness": 12, "min_score": 0.8, "censor": censor_on,
               "jumpcut": jumpcut, "bleep": bleep}

        # 1) Find candidates across the whole video: ~2x the requested clips, spread over 10-min windows.
        win = 600
        n_win = max(1, math.ceil(total / win))
        cfg["clips_per_segment"] = max(2, math.ceil(n_clips * 2 / n_win))
        candidates = []
        for i in range(n_win):
            t0 = i * win
            set_status(project, status=f"Buscando momentos… {i + 1}/{n_win}")
            _, sentences, words, moments = analyze(cfg, src, t0, min(win, total - t0))
            for m in moments:
                text = " ".join(s["text"] for s in sentences if s["end"] > m["start"] and s["start"] < m["end"])
                clip_words = [{**w, "start": w["start"] + t0, "end": w["end"] + t0} for w in words
                              if w["end"] > m["start"] and w["start"] < m["end"]]
                density = len(clip_words) / max(1.0, m["end"] - m["start"])
                candidates.append({"start": t0 + m["start"], "end": t0 + m["end"], "audio": m["score"],
                                   "density": density, "transcript": text, "words": clip_words})
        log("generar", f"{len(candidates)} momentos candidatos")
        if not candidates:
            set_status(project, status="No he encontrado momentos con voz en este vídeo.", done=True)
            return project

        # 2) Hooks + virality score. Talking speed and loud reactions matter; swearing is penalised.
        for i, c in enumerate(candidates):
            set_status(project, status=f"Escribiendo hooks… {i + 1}/{len(candidates)}")
            c["hook"], c["caption"], c["quality"] = generic_hook(cfg, c["transcript"], title,
                                                                 camp["creator"] if camp else None)
            c["raw"] = (c["audio"] + 0.6 * min(c["density"], 3.5) + 0.5 * c["quality"]
                        - min(2.0, 0.5 * profanity_count(c["transcript"])))
        top = max(c["raw"] for c in candidates)
        low = min(c["raw"] for c in candidates)
        for c in candidates:
            c["viral"] = int(round(40 + 59 * (c["raw"] - low) / max(1e-6, top - low)))
        candidates.sort(key=lambda c: c["viral"], reverse=True)

        # 3) Render the best ones, best first, so the panel fills up in ranking order.
        made = 0
        for c in candidates:
            if made >= n_clips:
                break
            set_status(project, status=f"Montando clips… {made + 1}/{n_clips}")
            clip_dir = project / "clips" / f"{int(c['start']):05d}"
            clip_dir.mkdir(exist_ok=True)
            layout = render_clip(src, c["start"], c["end"], c["words"], c["hook"], clip_dir, cfg, tpl)
            if not layout:
                shutil.rmtree(clip_dir, ignore_errors=True)  # don't leave a half-written clip.mp4 behind
                continue
            caption = censor(c["caption"]) if cfg.get("censor", True) else c["caption"]
            caption, tags = campaigns.apply(camp, caption, ["#shorts", "#viral", "#fyp"])
            write_json(clip_dir / "meta.json", {
                "id": clip_dir.name, "source": str(src), "start": round(c["start"], 2), "end": round(c["end"], 2),
                "viral": c["viral"], "quality": c["quality"], "hook": c["hook"], "caption": caption,
                "hashtags": tags, "campaign": camp["key"] if camp else None, "swears": profanity_count(c["transcript"]),
                "transcript": c["transcript"], "words": c["words"],
                "template": spec_of(tpl), "layout": layout, "created": time.time(),
            })
            made += 1
            log("generar", f"Clip {made}/{n_clips} · viralidad {c['viral']} · «{c['hook']}»")
        set_status(project, status=f"Listo: {made} clips", done=True)
    except Exception as e:
        set_status(project, status=f"Error: {e}", done=True)
        raise
    return project


def rerender_project_clip(cfg, clip_dir, tpl_spec=None):
    meta = json.loads((clip_dir / "meta.json").read_text(encoding="utf-8"))
    tpl = parse(tpl_spec or meta["template"])
    project = json.loads((clip_dir.parent.parent / "project.json").read_text(encoding="utf-8"))
    cfg = {**cfg, "min_brightness": 0, "censor": project.get("censor", True),
           "jumpcut": project.get("jumpcut", True), "bleep": project.get("bleep", True)}
    layout = render_clip(meta["source"], meta["start"], meta["end"], meta["words"], meta["hook"], clip_dir, cfg, tpl)
    if layout:
        meta["template"], meta["layout"] = spec_of(tpl), layout
        write_json(clip_dir / "meta.json", meta)
    log("rehacer", f"{clip_dir.name}: {'OK' if layout else 'falló'}")
    return bool(layout)

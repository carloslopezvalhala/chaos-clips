"""Find the best moments of a long VOD from its audio only, so only those minutes get downloaded as video."""
import json
import math
import subprocess
from pathlib import Path

from .common import ROOT, log, probe_duration, read_audio
from .detect import analyze, find_moments
from .text import profanity_count

SCANS = ROOT / "work" / "scans"


def download_audio(url):
    SCANS.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["yt-dlp", "--encoding", "utf-8", "--js-runtimes", "node", "--no-playlist", "-f", "ba/bestaudio/worst",
         "-x", "--audio-format", "m4a", "-o", str(SCANS / "%(id)s.%(ext)s"), "--print", "after_move:filepath", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    files = [l.strip() for l in res.stdout.splitlines() if l.strip()]
    if not files:
        raise RuntimeError(f"No se pudo descargar el audio: {res.stderr[-500:]}")
    return Path(files[-1])


def scan(cfg, url, top=5, language=None):
    """Returns the best `top` moments as dicts {start, end, score, transcript}, best first."""
    audio = download_audio(url)
    total = probe_duration(audio)
    cfg = {**cfg, "whisper_model": cfg.get("generator_whisper_model", "small"), "language": language,
           "clip_min_seconds": 20, "clip_max_seconds": 55, "pre_peak_seconds": 30, "post_peak_seconds": 16,
           "min_score": 0.8, "clips_per_segment": 3}
    found = []
    win = 600
    cache_dir = SCANS / f"{audio.stem}_transcripts"
    cache_dir.mkdir(exist_ok=True)
    for i in range(math.ceil(total / win)):
        t0 = i * win
        dur = min(win, total - t0)
        log("escanear", f"{audio.stem}: {int(t0 // 60)}–{int((t0 + dur) // 60)} min de {int(total // 60)}")
        cached = cache_dir / f"{i:03d}.json"
        if cached.exists():  # Whisper is the slow part; re-scans reuse the transcript
            sentences, words = json.loads(cached.read_text(encoding="utf-8"))
            moments = find_moments(cfg, read_audio(audio, t0, dur), sentences, words)
        else:
            _, sentences, words, moments = analyze(cfg, audio, t0, dur)
            cached.write_text(json.dumps([sentences, words]), encoding="utf-8")
        for m in moments:
            text = " ".join(s["text"] for s in sentences if s["end"] > m["start"] and s["start"] < m["end"])
            n_words = sum(1 for w in words if m["start"] <= w["start"] < m["end"])
            density = n_words / max(1.0, m["end"] - m["start"])
            score = m["score"] + 0.6 * min(density, 3.5) - min(2.0, 0.5 * profanity_count(text))
            found.append({"start": t0 + m["start"], "end": t0 + m["end"], "score": round(score, 2), "transcript": text})
    found.sort(key=lambda m: m["score"], reverse=True)
    return found[:top]


def hms(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"

import re

import numpy as np

from .common import read_audio, setup_cuda_dlls, log

HYPE_WORDS = {
    "oh my god": 2.0, "omg": 2.0, "what the": 2.0, "holy": 2.0, "no way": 2.0, "bro": 0.8,
    "run": 1.5, "scream": 1.5, "scared": 1.5, "help": 1.2, "wait": 0.8, "dude": 0.8,
    "fuck": 1.5, "shit": 1.2, "crazy": 1.0, "insane": 1.2, "dead": 1.0, "killer": 1.5,
    "lmao": 1.2, "hahaha": 1.5, "nah": 0.8, "yo": 0.6, "let's go": 1.5, "oh no": 2.0,
    "secret": 1.0, "never": 0.6, "million": 1.0, "money": 0.8, "truth": 1.0, "nobody": 0.6,
    # Spanish
    "dios mío": 2.0, "qué fuerte": 2.0, "no puede ser": 2.0, "madre mía": 2.0, "joder": 1.5,
    "increíble": 1.2, "brutal": 1.2, "en serio": 1.0, "tío": 0.6, "hostia": 1.5, "flipa": 1.5,
    "nadie": 0.6, "secreto": 1.0, "millones": 1.0, "dinero": 0.8, "verdad": 0.8, "jajaja": 1.5,
}

_model = None


def whisper(cfg):
    global _model
    if _model is None:
        setup_cuda_dlls()
        from faster_whisper import WhisperModel
        try:
            _model = WhisperModel(cfg["whisper_model"], device="cuda", compute_type="float16")
            log("whisper", "Usando la GPU")
        except Exception as e:  # no CUDA -> slower but works
            log("whisper", f"GPU no disponible ({e}); usando CPU")
            _model = WhisperModel(cfg["whisper_model"], device="cpu", compute_type="int8")
    return _model


def transcribe(cfg, audio):
    segs, _ = whisper(cfg).transcribe(audio, word_timestamps=True, vad_filter=True,
                                      language=cfg.get("language", "en") or None)
    sentences, words = [], []
    for s in segs:
        sentences.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": w.start, "end": w.end, "word": w.word.strip()})
    return sentences, words


def loudness_curve(audio, sr=16000, hop=0.5):
    n = int(sr * hop)
    frames = len(audio) // n
    if frames == 0:
        return np.zeros(0), np.zeros(0)
    rms = np.sqrt(np.mean(audio[: frames * n].reshape(frames, n) ** 2, axis=1) + 1e-10)
    db = 20 * np.log10(rms)
    # The baseline comes from frames that actually have sound: long stretches of digital silence
    # (mic muted, ad break) would otherwise make every normal sentence look like a huge spike.
    voiced = db[db > -60]
    if len(voiced) < len(db) * 0.1:
        return np.zeros(len(db)), db
    med = np.median(voiced)
    mad = max(float(np.median(np.abs(voiced - med))), 1.0)
    return np.clip((db - med) / (1.4826 * mad), -5, 8), db


def find_moments(cfg, audio, sentences, words, sr=16000, hop=0.5):
    """Scores each 0.5 s window by loudness spikes + hype words and returns the best non-overlapping peaks."""
    loud, db = loudness_curve(audio, sr, hop)
    if len(loud) == 0:
        return []
    # Spikes are relative to the segment, so a near-silent empty room still has "peaks".
    # Real moments need actual volume and actual talking.
    if np.percentile(db, 90) < cfg.get("min_dbfs", -38):
        log("detectar", "Trozo casi en silencio; no hay momentos")
        return []
    kernel = np.ones(6) / 6  # 3 s smoothing
    score = np.convolve(np.clip(loud, 0, None), kernel, mode="same")
    for s in sentences:
        text = s["text"].lower()
        bonus = sum(w for k, w in HYPE_WORDS.items() if k in text)
        bonus += 0.5 * text.count("!") + (1.0 if re.search(r"\b(a{3,}|ah{2,})\b", text) else 0)
        i0, i1 = int(s["start"] / hop), int(s["end"] / hop) + 1
        score[i0:i1] += min(bonus, 4.0) * 0.6

    total = len(audio) / sr
    moments, taken = [], np.zeros(len(score), bool)
    gap = int((cfg["clip_max_seconds"] + 5) / hop)
    for idx in np.argsort(score)[::-1]:
        if len(moments) >= cfg["clips_per_segment"] or score[idx] < cfg["min_score"]:
            break
        if taken[idx]:
            continue
        peak = idx * hop
        start, end = snap_window(cfg, peak, sentences, total)
        start, end = trim_window(cfg, start, end, peak, sentences, score, hop)
        if end - start < cfg["clip_min_seconds"]:
            continue
        n_words = sum(1 for w in words if start <= w["start"] < end)
        clip_db = db[int(start / hop): int(end / hop) + 1]
        if n_words < cfg.get("min_words", 12) or np.percentile(clip_db, 75) < cfg.get("min_dbfs", -38):
            taken[idx] = True
            continue
        taken[max(0, idx - gap): idx + gap] = True
        moments.append({"peak": peak, "start": start, "end": end, "score": float(score[idx])})
    return moments


def snap_window(cfg, peak, sentences, total):
    start = max(0.0, peak - cfg["pre_peak_seconds"])
    end = min(total, peak + cfg["post_peak_seconds"])
    # Start on a sentence boundary so the clip doesn't open mid-word.
    for s in sentences:
        if s["start"] <= start <= s["end"] and start - s["start"] < 5:
            start = s["start"]
            break
    for s in sentences:
        if s["start"] <= end <= s["end"] and s["end"] - end < 5:
            end = s["end"]
            break
    end = min(end, start + cfg["clip_max_seconds"], total)
    return round(start, 2), round(end + 0.3, 2)


FILLER = {"yeah", "yes", "okay", "ok", "bro", "man", "um", "uh", "alright", "all", "right", "so", "like", "yo",
          "hey", "thank", "thanks", "you", "this", "way", "wait", "my", "bad", "hold", "on", "oh", "mm", "hmm",
          "vale", "sí", "tío", "bueno", "eh", "pues"}


def _is_filler(sentence):
    words = re.findall(r"[^\W\d_]+", sentence["text"].lower())
    return len(words) <= 3 or all(w in FILLER for w in words)


def trim_window(cfg, start, end, peak, sentences, score, hop):
    """Viral clips open on the action and stop at the payoff: drop filler sentences at the start
    ("yeah… my bad bro…") and low-energy sentences trailing after the peak ("back up, this way, thanks")."""
    min_len = cfg["clip_min_seconds"]
    inside = [s for s in sentences if s["end"] > start and s["start"] < end]
    while len(inside) > 1 and _is_filler(inside[0]):
        nxt = inside[1]["start"]
        if peak - nxt < 4 or end - nxt < min_len:
            break
        inside.pop(0)
        start = nxt
    while len(inside) > 1:
        last = inside[-1]
        seg = score[int(last["start"] / hop): int(last["end"] / hop) + 1]
        weak = _is_filler(last) or (len(seg) and float(np.mean(seg)) < 0.3)
        new_end = inside[-2]["end"] + 0.3
        if not weak or last["start"] < peak + 3 or new_end - start < min_len:
            break
        inside.pop()
        end = new_end
    return round(start, 2), round(end, 2)


def analyze(cfg, path, t0, duration):
    audio = read_audio(path, t0, duration)
    sentences, words = transcribe(cfg, audio)
    return audio, sentences, words, find_moments(cfg, audio, sentences, words)

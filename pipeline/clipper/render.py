import subprocess
from pathlib import Path

import cv2
import numpy as np

from .common import ROOT, log
from .text import censor, profanity_count

W, H = 1080, 1920
FULL_H = 608                 # 16:9 frame scaled to 1080 wide
A_TOP, A_ZOOM_Y = 240, 848   # layout A: hook band, full frame, zoom panel
ZOOM_H = H - A_ZOOM_Y        # 1072
B_FULL_Y = (H - FULL_H) // 2
PANEL_H = H // 2             # podcast: two 1080x960 panels

# Where the hook and the captions sit for each layout (y of their centre).
POSITIONS = {"A": (120, 1300), "B": (520, 1420), "fill": (330, 1350), "podcast": (140, 960)}

_detector = None


def find_faces(path, start, end):
    """Samples ~2 frames/s. Returns (main, pair, size, brightness, shots):
    main = median centre of the largest face, pair = (left, right) speakers for podcast layout,
    shots = [(t_from, t_to, face_or_None)] relative to start, one entry per camera shot."""
    global _detector
    if _detector is None:
        _detector = cv2.FaceDetectorYN.create(str(ROOT / "models" / "yunet.onnx"), "", (960, 540), 0.7)
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(round(fps / 2)))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    samples, size, lum, prev, i = [], None, [], None, 0
    n_frames = int((end - start) * fps)
    while i < n_frames:
        if not cap.grab():
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                size = frame.shape[1], frame.shape[0]
                small = cv2.resize(frame, (960, 540))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                lum.append(gray.mean())
                thumb = cv2.resize(gray, (64, 36)).astype(np.float32)
                cut = prev is not None and float(np.mean(np.abs(thumb - prev))) > 28
                prev = thumb
                _, det = _detector.detect(small)
                k = size[0] / 960
                faces = [] if det is None else [((x + w / 2) * k, (y + h / 2) * k, w * k)
                                                for x, y, w, h in det[:, :4] if w * k > size[0] * 0.03]
                samples.append((i / fps, cut, faces))
        i += 1
    cap.release()
    if size is None:
        return None, None, None, 0.0, []
    brightness = float(np.median(lum)) if lum else 0.0
    med = lambda fs: tuple(float(v) for v in np.median(np.array(fs), axis=0))

    largest = [max(f, key=lambda v: v[2]) for _, _, f in samples if f]
    left = [max([v for v in f if v[0] < size[0] / 2], key=lambda v: v[2]) for _, _, f in samples
            if any(v[0] < size[0] / 2 for v in f) and any(v[0] >= size[0] / 2 for v in f)]
    right = [max([v for v in f if v[0] >= size[0] / 2], key=lambda v: v[2]) for _, _, f in samples
             if any(v[0] < size[0] / 2 for v in f) and any(v[0] >= size[0] / 2 for v in f)]
    main = med(largest) if len(largest) >= max(2, len(samples) // 4) else None
    pair = (med(left), med(right)) if len(left) >= max(2, len(samples) // 3) else None

    # Split into camera shots and frame each shot on its own largest face.
    shots, cur = [], []
    for s in samples:
        if s[1] and cur:
            shots.append(cur)
            cur = []
        cur.append(s)
    if cur:
        shots.append(cur)
    out = []
    for k, shot in enumerate(shots):
        faces = [max(f, key=lambda v: v[2]) for _, _, f in shot if f]
        t_from = 0.0 if k == 0 else shot[0][0]
        t_to = shots[k + 1][0][0] if k + 1 < len(shots) else end - start + 1
        out.append((t_from, t_to, med(faces) if faces else None))
    return main, pair, size, brightness, out


def crop_x_expr(shots, size, cw, fallback):
    """ffmpeg expression giving the crop x for each shot, so every camera cut is re-framed on the face."""
    sw = size[0]
    xs = []
    for t_from, t_to, face in shots:
        fx = face[0] if face else (fallback[0] if fallback else sw / 2)
        xs.append((t_to, int(np.clip(fx - cw / 2, 0, sw - cw))))
    if len(set(x for _, x in xs)) <= 1:
        return str(xs[0][1]) if xs else str((sw - cw) // 2)
    expr = str(xs[-1][1])
    for t_to, x in reversed(xs[:-1]):
        expr = f"if(lt(t,{t_to:.2f}),{x},{expr})"
    return f"'{expr}'"


def crop_around(face, size, cw, ch, face_at=0.4):
    sw, sh = size
    cw, ch = min(cw, sw) // 2 * 2, min(ch, sh) // 2 * 2
    fx, fy = (face[0], face[1]) if face else (sw / 2, sh / 2)
    x = int(np.clip(fx - cw / 2, 0, sw - cw))
    y = int(np.clip(fy - ch * face_at, 0, sh - ch))
    return cw, ch, x, y


def ass_time(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def clean(s, do_censor=True):
    # Burned-in swear words get Shorts age-restricted, so on-screen text is censored by default.
    s = censor(s) if do_censor else s
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


STYLE_FMT = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
             "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
             "Alignment, MarginL, MarginR, MarginV, Encoding")
STYLES = {
    # captions
    "karaoke": "Arial Black,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3",
    "hormozi": "Arial Black,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8,4",
    "pop": "Arial Black,124,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,9,4",
    "caja": "Arial,64,&H00FFFFFF,&H00FFFFFF,&H40000000,&H40000000,-1,0,0,0,100,100,0,0,3,16,0",
    "minimal": "Segoe UI Semibold,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,0,3",
    # hooks
    "caja_blanca": "Arial Black,58,&H00111111,&H00111111,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0",
    "caja_negra": "Arial Black,58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,18,0",
    "amarillo": "Arial Black,76,&H0000D7FF,&H0000D7FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8,3",
}
CHUNK = {"karaoke": 3, "hormozi": 2, "pop": 1, "caja": 5, "minimal": 4}
HIGHLIGHT = {"karaoke": ["&H00D7FF&"], "hormozi": ["&H7FFF00&", "&H00D7FF&"]}  # BGR: yellow, green


def chunk_words(words, size):
    chunks, cur = [], []
    for w in words:
        if cur and (len(cur) == size or w["start"] - cur[-1]["end"] > 0.6):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def caption_events(words, style, do_censor):
    events = []
    for ci, chunk in enumerate(chunk_words(words, CHUNK[style])):
        if style in HIGHLIGHT:
            colour = HIGHLIGHT[style][ci % len(HIGHLIGHT[style])]
            for i, w in enumerate(chunk):
                parts = []
                for j, o in enumerate(chunk):
                    txt = clean(o["word"], do_censor).upper()
                    parts.append(f"{{\\c{colour}}}{txt}{{\\c&HFFFFFF&}}" if j == i else txt)
                events.append([w["start"], w["end"] + 0.25, " ".join(parts)])
        elif style == "pop":
            w = chunk[0]
            events.append([w["start"], w["end"] + 0.25,
                           "{\\fscx130\\fscy130\\t(0,90,\\fscx100\\fscy100)}" + clean(w["word"], do_censor).upper()])
        else:
            text = " ".join(clean(o["word"], do_censor) for o in chunk)
            events.append([chunk[0]["start"], chunk[-1]["end"] + 0.25, text.lower() if style == "minimal" else text])
    # Only one caption on screen at a time: each one ends no later than the next one starts.
    events.sort(key=lambda e: e[0])
    out = []
    for k, (start, end, text) in enumerate(events):
        if k + 1 < len(events):
            nxt = events[k + 1][0]
            end = min(end, nxt)
            if nxt - end < 0.6:  # tiny gap between words: hold until the next one instead of flickering
                end = nxt
        if end - start >= 0.04:
            out.append((start, end, text))
    return out


def build_ass(words, hook, duration, layout, tpl, hook_seconds=0, do_censor=True):
    hook_y, sub_y = POSITIONS[layout]
    subs, hook_style = tpl["subs"], tpl["hook"]
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
             "[V4+ Styles]", STYLE_FMT,
             f"Style: Sub,{STYLES[subs]},5,70,70,0,1"]
    if hook_style != "ninguno":
        lines.append(f"Style: Hook,{STYLES[hook_style]},5,90,90,0,1")
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    if hook_style != "ninguno" and hook:
        hook_end = duration if not hook_seconds else min(hook_seconds, duration)
        text = clean(hook, do_censor)
        text = text.upper() if hook_style == "amarillo" else text
        lines.append(f"Dialogue: 1,{ass_time(0)},{ass_time(hook_end)},Hook,,0,0,0,,{{\\pos(540,{hook_y})}}{text}")
    for start, end, text in caption_events(words, subs, do_censor):
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Sub,,0,0,0,,{{\\pos(540,{sub_y})}}{text}")
    return "\n".join(lines) + "\n"


def keep_segments(words, duration, max_gap=0.8, pad=0.25):
    """Jump cuts: the parts of the clip to keep, dropping pauses longer than max_gap between words."""
    if not words:
        return [(0.0, duration)]
    segs = [[max(0.0, words[0]["start"] - pad), words[0]["end"] + pad]]
    for w in words[1:]:
        if w["start"] - segs[-1][1] > max_gap - 2 * pad:
            segs.append([w["start"] - pad, w["end"] + pad])
        else:
            segs[-1][1] = max(segs[-1][1], w["end"] + pad)
    segs[0][0] = 0.0 if segs[0][0] < 0.6 else segs[0][0]
    segs[-1][1] = min(duration, segs[-1][1] + 0.3)
    return [(round(a, 3), round(min(b, duration), 3)) for a, b in segs if b - a > 0.05]


def remap(t, segs):
    """Time t of the original clip -> time in the jump-cut clip."""
    out = 0.0
    for a, b in segs:
        if t <= a:
            return out
        if t <= b:
            return out + (t - a)
        out += b - a
    return out


def between_expr(intervals):
    return "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in intervals)


def encoder_args():
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "h264_nvenc" in probe:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


_enc = None


def render_clip(src, start, end, words, hook, out_dir, cfg, tpl=None):
    """Cuts [start, end] from src into a 1080x1920 vertical clip using a template (layout + captions + hook).
    Without a template it uses the live-stream look, where the full frame (and the stream's logo) is always visible."""
    global _enc
    _enc = _enc or encoder_args()
    tpl = tpl or {"layout": cfg["layout"], "subs": "karaoke", "hook": "caja_blanca"}
    duration = end - start
    face, pair, size, brightness, shots = find_faces(src, start, end)
    if size is None:
        log("render", "No se pudo leer el vídeo")
        return None
    if brightness < cfg.get("min_brightness", 40):
        log("render", f"Imagen demasiado oscura (brillo {brightness:.0f}); descarto el momento")
        return None

    layout = tpl["layout"]
    if layout == "auto":
        layout = "A" if face else "B"
    if layout == "A" and not face:
        layout = "B"
    if layout == "podcast" and not pair:
        layout = "fill"  # only one person on screen

    rel_words = [{**w, "start": w["start"] - start, "end": w["end"] - start} for w in words
                 if w["end"] > start and w["start"] < end]

    # Jump cuts: drop dead air, then move captions (and bleeps) onto the shortened timeline.
    segs = keep_segments(rel_words, duration) if cfg.get("jumpcut", True) else [(0.0, duration)]
    cut = len(segs) > 1 or segs[0][0] > 0.05 or segs[-1][1] < duration - 0.05
    out_words = [{**w, "start": remap(w["start"], segs), "end": remap(w["end"], segs)} for w in rel_words] if cut else rel_words
    out_duration = sum(b - a for a, b in segs) if cut else duration

    ass = build_ass(out_words, hook, out_duration, layout, tpl, cfg.get("hook_seconds", 0), cfg.get("censor", True))
    (out_dir / "subs.ass").write_text(ass, encoding="utf-8")

    # Audible swearing gets Shorts age-restricted even when the captions are censored: bleep it.
    bleeps = [(max(0.0, w["start"] - 0.05), w["end"] + 0.05) for w in out_words
              if cfg.get("bleep", True) and cfg.get("censor", True) and profanity_count(w["word"])]
    vsel = f"select='{between_expr(segs)}',setpts=N/FRAME_RATE/TB," if cut else ""
    audio = "[0:a]" + (f"aselect='{between_expr(segs)}',asetpts=N/SR/TB," if cut else "") + "aresample=48000"
    if bleeps:
        audio += (f",volume=0:enable='{between_expr(bleeps)}'[am];"
                  f"sine=frequency=1000:sample_rate=48000,volume='0.3*({between_expr(bleeps)})':eval=frame[bp];"
                  f"[am][bp]amix=inputs=2:duration=first:normalize=0")
    audio += ",loudnorm=I=-14:TP=-1.5:LRA=11[a]"

    sw, sh = size
    bg = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:3,eq=brightness=-0.12"
    full = f"scale={W}:{FULL_H}:force_original_aspect_ratio=decrease,pad={W}:{FULL_H}:(ow-iw)/2:(oh-ih)/2"
    if layout == "A":
        cw, ch, x, y = crop_around(face, size, int(sh * 0.62 * W / ZOOM_H), int(sh * 0.62))
        graph = (f"[0:v]split=3[s1][s2][s3];[s1]{bg}[bg];[s2]{full}[full];"
                 f"[s3]crop={cw}:{ch}:{x}:{y},scale={W}:{ZOOM_H}[zoom];"
                 f"[bg][full]overlay=0:{A_TOP}[t];[t][zoom]overlay=0:{A_ZOOM_Y},ass=subs.ass[v]")
    elif layout == "B":
        graph = f"[0:v]split=2[s1][s2];[s1]{bg}[bg];[s2]{full}[full];[bg][full]overlay=0:{B_FULL_Y},ass=subs.ass[v]"
    elif layout == "podcast":
        ch = int(sh * 0.7)
        boxes = [crop_around(f, size, int(ch * W / PANEL_H), ch) for f in pair]
        crops = ";".join(f"[s{i}]crop={cw}:{ch2}:{x}:{y},scale={W}:{PANEL_H}[p{i}]" for i, (cw, ch2, x, y) in enumerate(boxes))
        graph = f"[0:v]split=2[s0][s1];{crops};[p0][p1]vstack,ass=subs.ass[v]"
    else:  # fill
        cw, ch, x, y = crop_around(face, size, int(sh * 9 / 16), sh)
        x = crop_x_expr(shots, size, cw, face)
        graph = f"[0:v]crop={cw}:{ch}:{x}:{y},scale={W}:{H},ass=subs.ass[v]"

    # ffmpeg runs inside out_dir (for the relative subs.ass path), so the source must be absolute.
    graph = graph.replace(",ass=subs.ass[v]", f",{vsel}ass=subs.ass[v]") + ";" + audio
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{duration:.2f}", "-i", str(Path(src).resolve()),
           "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-r", "30", *_enc,
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "clip.mp4"]
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True)
    if res.returncode != 0:
        log("render", f"ffmpeg falló: {res.stderr[-500:]}")
        return None
    return layout

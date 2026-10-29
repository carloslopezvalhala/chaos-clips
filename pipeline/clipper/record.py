import subprocess
import time

from .common import SEGMENTS, log


def stream_urls(page_url):
    """Media URLs of a live stream (YouTube, Twitch, Kick…): [video, audio] or a single muxed URL, plus its title."""
    out = subprocess.run(
        ["yt-dlp", "--encoding", "utf-8", "--js-runtimes", "node", "--no-playlist", "--print", "title", "--print", "urls",
         "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--match-filter", "is_live", page_url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    urls = [l for l in lines if l.startswith("http")]
    title = next((l for l in lines if not l.startswith("http")), "")
    return (urls, title) if urls else (None, "")


def record_forever(cfg, stop):
    """Records the live stream into N-minute .ts segments. Restarts when the HLS URL expires or the stream drops."""
    seg_s = int(cfg["segment_minutes"] * 60)
    while not stop.is_set():
        urls, title = stream_urls(cfg["stream_url"])
        if not urls:
            log("grabar", "Ese directo no está emitiendo ahora mismo. Reintento en 2 min.")
            stop.wait(120)
            continue
        cfg["stream_title"] = title  # shared with the processor thread, used for hooks
        log("grabar", f"Grabando «{title}»…")
        inputs = ["-i", urls[0]] + (["-i", urls[1], "-map", "0:v", "-map", "1:a"] if len(urls) > 1
                                    else ["-map", "0:v", "-map", "0:a"])
        proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", *inputs, "-c", "copy",
             "-f", "segment", "-segment_time", str(seg_s), "-reset_timestamps", "1",
             "-strftime", "1", str(SEGMENTS / "%Y%m%d_%H%M%S.ts")],
            stdin=subprocess.DEVNULL,
        )
        while proc.poll() is None and not stop.is_set():
            time.sleep(2)
        if proc.poll() is None:
            proc.terminate()
        log("grabar", "La grabación se cortó; reconectando.")
        stop.wait(5)

import glob
import json
import os
import site
import subprocess
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEGMENTS = ROOT / "segmentos"
QUEUE = ROOT / "cola"
READY = ROOT / "listos"
STATE = ROOT / "estado.json"

for d in (SEGMENTS, QUEUE, READY):
    d.mkdir(exist_ok=True)

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def setup_cuda_dlls():
    # cuBLAS/cuDNN come from the nvidia-* pip wheels; Windows needs their bin dirs on the DLL path.
    for sp in site.getsitepackages():
        for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


LIVE_LOCK = ROOT / "directo.pid"


def pid_alive(pid):
    # os.kill(pid, 0) would *terminate* the process on Windows, so ask the OS directly.
    import ctypes
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
    k32.CloseHandle(handle)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def live_pid():
    """PID of the running live job, or None."""
    try:
        pid = int(LIVE_LOCK.read_text())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"processed": [], "published": []}


def save_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out) if out and out != "N/A" else 0.0


def read_audio(path, start=0.0, duration=None, sr=16000):
    cmd = ["ffmpeg", "-loglevel", "error", "-ss", f"{start:.3f}"]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", str(path), "-vn", "-f", "s16le", "-ac", "1", "-ar", str(sr), "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0

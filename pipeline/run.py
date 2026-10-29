"""Favorited Mansion clipper.

  python run.py directo            graba el directo, saca clips y deja uno listo cada hora
  python run.py video RUTA.mp4     saca clips de un vídeo ya descargado
  python run.py vod URL [--desde 1:30:00 --hasta 2:30:00]   descarga un trozo del VOD y lo procesa
  python run.py publicar           solo suelta el mejor clip de la cola ahora mismo
  python run.py rehacer CARPETA…   vuelve a montar clips ya hechos (mismo corte y hook)
"""
import argparse
import subprocess
import sys
import threading
from pathlib import Path

from clipper.common import ROOT, load_config, log


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("directo")
    v = sub.add_parser("video")
    v.add_argument("ruta")
    d = sub.add_parser("vod")
    d.add_argument("url")
    d.add_argument("--desde")
    d.add_argument("--hasta")
    sub.add_parser("publicar")
    r = sub.add_parser("rehacer")
    r.add_argument("carpetas", nargs="+")
    r.add_argument("--nuevo-hook", action="store_true", help="también genera hook y descripción nuevos")
    g = sub.add_parser("generar")
    g.add_argument("url")
    g.add_argument("--clips", type=int, default=10)
    g.add_argument("--plantilla", default="viral")
    g.add_argument("--desde")
    g.add_argument("--hasta")
    g.add_argument("--idioma", default="", help="en, es… vacío = automático")
    g.add_argument("--min", type=int, default=20)
    g.add_argument("--max", type=int, default=55)
    g.add_argument("--sin-censura", action="store_true")
    g.add_argument("--sin-cortes", action="store_true", help="no quitar los silencios")
    g.add_argument("--sin-pitido", action="store_true", help="no pitar los tacos en el audio")
    g.add_argument("--campana", help="clave de campaña de campanas.json (speed, kaicenat, lacy…)")
    sc = sub.add_parser("escanear", help="busca los mejores momentos de un VOD largo usando solo el audio")
    sc.add_argument("url")
    sc.add_argument("--top", type=int, default=5)
    sc.add_argument("--idioma", default="")
    rg = sub.add_parser("regenerar")
    rg.add_argument("carpeta")
    rg.add_argument("--plantilla")
    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == "directo":
        import os
        from clipper.common import LIVE_LOCK, live_pid
        if (pid := live_pid()) and pid != os.getpid():
            sys.exit(f"Ya hay un directo en marcha (proceso {pid}). Páralo antes de iniciar otro.")
        LIVE_LOCK.write_text(str(os.getpid()))
        from clipper.process import process_segments_forever
        from clipper.publish import publish_forever
        from clipper.record import record_forever

        stop = threading.Event()
        threads = [threading.Thread(target=f, args=(cfg, stop), daemon=True)
                   for f in (record_forever, process_segments_forever, publish_forever)]
        for t in threads:
            t.start()
        log("main", "Funcionando. Ctrl+C para parar.")
        try:
            while True:
                threads[0].join(1)
        except KeyboardInterrupt:
            stop.set()
            log("main", "Parando…")

    elif args.cmd == "video":
        from clipper.process import process_file
        process_file(cfg, Path(args.ruta).resolve())

    elif args.cmd == "vod":
        from clipper.process import process_file
        out_dir = ROOT / "vods"
        out_dir.mkdir(exist_ok=True)
        cmd = ["yt-dlp", "--js-runtimes", "node", "-f", "bv*[height<=1080]+ba", "--merge-output-format", "mp4",
               "-o", str(out_dir / "%(id)s_%(section_start)s.%(ext)s")]
        if args.desde or args.hasta:
            cmd += ["--download-sections", f"*{args.desde or '0'}-{args.hasta or 'inf'}"]
        res = subprocess.run(cmd + ["--print", "after_move:filepath", args.url], capture_output=True, text=True)
        files = [l for l in res.stdout.splitlines() if l.strip()]
        if not files:
            sys.exit(f"No se pudo descargar el VOD:\n{res.stderr[-800:]}")
        process_file(cfg, Path(files[-1]))

    elif args.cmd == "rehacer":
        from clipper.process import rerender
        for c in args.carpetas:
            rerender(cfg, Path(c).resolve(), args.nuevo_hook)

    elif args.cmd == "generar":
        from clipper.generator import generate
        generate(cfg, args.url, args.clips, args.plantilla, args.desde, args.hasta, args.idioma or None,
                 args.min, args.max, not args.sin_censura, args.campana,
                 not args.sin_cortes, not args.sin_pitido)

    elif args.cmd == "escanear":
        import json
        from clipper.scan import hms, scan
        best = scan(cfg, args.url, args.top, args.idioma or None)
        for m in best:
            print(f"{hms(m['start'])}-{hms(m['end'])} | nota {m['score']} | {m['transcript'][:140]}")
        print("JSON " + json.dumps(best, ensure_ascii=False))

    elif args.cmd == "regenerar":
        from clipper.generator import rerender_project_clip
        rerender_project_clip(cfg, Path(args.carpeta).resolve(), args.plantilla)

    elif args.cmd == "publicar":
        from clipper.publish import release_best
        if not release_best(cfg):
            log("publicar", "No hay clips en la cola.")


if __name__ == "__main__":
    main()

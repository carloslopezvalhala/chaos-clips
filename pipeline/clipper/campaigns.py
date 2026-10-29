"""Clipping campaigns: who the clip is about and which name/hashtags the caption must carry."""
import json

from .common import ROOT

FILE = ROOT / "campanas.json"

DEFAULTS = [
    {"key": "speed", "name": "IShowSpeed × Expedia", "creator": "IShowSpeed", "hashtags": ["#IShowSpeed", "#Expedia"],
     "template": "desenfocado",
     "notes": "Solo el stream Unpack del 14/10. La maleta amarilla tiene que verse. Di bien el destino en la descripción. Sin X."},
    {"key": "kaicenat", "name": "Kai Cenat", "creator": "Kai Cenat", "hashtags": ["#KaiCenat"], "template": "viral",
     "notes": "Solo streams del 21 al 31 de octubre. Sin X."},
    {"key": "lacy", "name": "Lacy", "creator": "Lacy", "hashtags": ["#Lacy"], "template": "viral",
     "notes": "Cualquier contenido de Lacy. Mínimo 1M de vistas en total."},
]


def load():
    if not FILE.exists():
        save(DEFAULTS)
    return json.loads(FILE.read_text(encoding="utf-8"))


def save(items):
    FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def get(key):
    return next((c for c in load() if c["key"] == key), None) if key else None


def apply(campaign, caption, hashtags):
    """Caption must name the creator; campaign hashtags go first. Returns (caption, hashtags)."""
    if not campaign:
        return caption, hashtags
    creator = campaign["creator"]
    if creator.lower() not in caption.lower():
        caption = f"{creator}: {caption}" if caption else creator
    tags = list(campaign["hashtags"]) + [t for t in hashtags if t.lower() not in {h.lower() for h in campaign["hashtags"]}]
    return caption, tags[:5]

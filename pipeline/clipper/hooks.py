import json
import os
import random
import re
from datetime import date, datetime, timedelta, timezone

from .common import load_state, log, save_state
from .text import censor

TEMPLATE_HOOKS = {
    "scare": [
        "nobody in this house was ready for that", "watch the corner of the screen",
        "this halloween mansion is not okay", "the scream at the end",
        "he was NOT ready", "turn your volume up for this",
        "they said this house was haunted", "i would've left the mansion right here",
        "the way everyone ran", "this is why nobody sleeps in this house",
        "wait for it", "who screamed like that",
    ],
    "funny": [
        "i can't stop replaying this", "this is why you don't trust streamers",
        "the timing on this is perfect", "he really said that on stream",
        "nobody was prepared for this answer", "this mansion is pure chaos",
        "bro thought nobody would notice", "the face he makes at the end",
        "chat could not believe this", "this went left so fast",
        "12 streamers in one house was a mistake", "they're never living this down",
    ],
    "drama": [
        "it got personal real quick", "nobody expected that answer",
        "12 streamers. 1 mansion. 3 days.", "the tension in this room",
        "he said it to his face", "this is where it started going wrong",
        "you can feel the awkwardness", "they put 12 streamers in a halloween mansion for 3 days",
        "the vibe changed instantly", "someone in this house is lying",
        "this conversation got real", "the team draft got personal",
    ],
}

CAPTIONS = [
    "{who} in the halloween mansion is something else",
    "12 streamers, one haunted mansion, zero chill",
    "day {day} in the favorited mansion and it's already chaos",
    "{who} did not sign up for this",
    "the favorited mansion never misses",
    "this is what happens when you lock streamers in a haunted house",
    "{who} really said that",
    "3 days, 12 streamers, 1 halloween mansion",
    "streamers + haunted mansion = this",
    "nobody in this house is getting sleep tonight",
    "{who} vs the halloween mansion",
    "the favorited mansion is pure chaos",
    "this moment from the halloween mansion stream",
    "the mansion got to {who}",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "On-screen hook, lowercase, max 9 words"},
        "caption": {"type": "string", "description": "Post caption, 1-2 short sentences, names the creators heard"},
        "quality": {"type": "integer", "description": "1-10: how likely this clip is to go viral"},
    },
    "required": ["hook", "caption", "quality"],
    "additionalProperties": False,
}


def _prompt(transcript, cast, recent):
    avoid = "\n".join(f"- {h}" for h in recent[-25:]) or "(none yet)"
    return f"""You write hooks for short vertical clips (TikTok/Reels/Shorts) from "The Favorited Mansion": a 3-day Halloween livestream where 12 streamers live in a haunted mansion and compete in games (team draft, hide & seek, maze, murder mystery, blindfolded cooking, escape room, ghost hunting, fear factor, battles).

Cast: {", ".join(cast)}.

Transcript of the clip (auto-generated, may contain errors):
<transcript>
{transcript}
</transcript>

Hooks already used on this channel. Yours must be clearly different in wording and angle:
{avoid}

Write:
- hook: the on-screen text for the first seconds. Lowercase, max 9 words, curiosity or shock, US internet slang ok. Only describe what actually happens in the transcript; never invent events. No emojis, no hashtags, no swear words.
- caption: 1-2 short sentences for the post description, specific to this clip. Name a cast member only if they are clearly named or identifiable in the transcript. No swear words.
- quality: 1-10 honest rating of how gripping this moment is for someone scrolling (boring small talk = 1-3)."""


def names_in(transcript, cast):
    found = []
    for person in cast:
        for token in re.findall(r"[A-Za-z]+", person.split("(")[0]) + re.findall(r"\((\w+)\)", person):
            if len(token) > 2 and re.search(rf"\b{re.escape(token)}\b", transcript, re.I):
                found.append(person.split(" (")[0])
                break
    return found


def hashtags(cfg):
    base = cfg["hashtags"][:1]
    pool = cfg.get("hashtag_pool", cfg["hashtags"][1:])
    return base + random.sample(pool, min(3, len(pool)))


def make_hook(cfg, transcript):
    """Returns (hook, caption, quality), never repeating a hook already used on the channel."""
    state = load_state()
    used = state.setdefault("used_hooks", [])
    result = None
    if os.environ.get("ANTHROPIC_API_KEY") and transcript.strip():
        try:
            result = _claude_hook(cfg, transcript, used)
        except Exception as e:
            log("hook", f"Claude falló ({type(e).__name__}: {e}); uso plantilla")
    if result is None:
        result = _template_hook(cfg, transcript, state)
    hook, caption, quality = censor(result[0]), censor(result[1]), result[2]
    used.append(hook)
    state["used_hooks"] = used[-300:]
    save_state(state)
    return hook, caption, quality


def _claude_hook(cfg, transcript, used):
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=cfg["claude_model"],
        max_tokens=2000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": _prompt(transcript, cfg["cast"], used)}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("refusal")
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)
    return data["hook"].strip().lower(), data["caption"].strip(), int(data["quality"])


def _least_used(options, used):
    # Unused options first; once all are used, the ones used longest ago.
    last = {h: i for i, h in enumerate(used)}
    fresh = [o for o in options if o not in last]
    return random.choice(fresh) if fresh else min(options, key=lambda o: last[o])


def _template_hook(cfg, transcript, state):
    t = transcript.lower()
    if any(k in t for k in ("scream", "scared", "run", "oh my god", "help", "what the", "ghost")):
        kind = "scare"
    elif any(k in t for k in ("haha", "lmao", "bro", "dude")):
        kind = "funny"
    else:
        kind = "drama"
    hook = _least_used(TEMPLATE_HOOKS[kind], state.get("used_hooks", []))

    names = names_in(transcript, cfg["cast"])
    options = CAPTIONS if names else [c for c in CAPTIONS if "{who}" not in c]
    used_caps = state.setdefault("used_captions", [])
    template = _least_used(options, used_caps)
    used_caps.append(template)
    state["used_captions"] = used_caps[-100:]
    day = min(3, max(1, (datetime.now(timezone(timedelta(hours=-7))).date() - date(2026, 10, 20)).days + 1))
    caption = template.format(who=random.choice(names) if names else "", day=day)
    return hook, caption, 5

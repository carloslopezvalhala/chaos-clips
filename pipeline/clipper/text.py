import re

# Stem -> masked form. Matching is by word prefix, so "fucking", "shitty", "bitches" are caught too.
PROFANITY = {
    "motherfuck": "m*therf*ck", "fuck": "f*ck", "shit": "sh*t", "bitch": "b*tch", "asshole": "a**hole",
    "dick": "d*ck", "pussy": "p*ssy", "cunt": "c*nt", "nigg": "n****", "whore": "wh*re", "slut": "sl*t",
    "bastard": "b*stard", "cock": "c*ck", "retard": "r*tard", "fag": "f*g",
    # Spanish
    "puta": "p*ta", "puto": "p*to", "mierda": "m*erda", "coño": "c*ño", "joder": "j*der",
    "gilipoll": "g*lipoll", "cabrón": "c*brón", "cabrona": "c*brona", "polla": "p*lla", "hostia": "h*stia",
}
_word = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")


def _mask(word):
    low = word.lower()
    for stem, masked in PROFANITY.items():
        if low.startswith(stem):
            out = masked + low[len(stem):]
            return out.upper() if word.isupper() else out
    return None


def censor(text):
    return _word.sub(lambda m: _mask(m.group()) or m.group(), text)


def profanity_count(text):
    return sum(1 for w in _word.findall(text) if _mask(w))

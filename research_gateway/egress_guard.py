"""Egress Guard: filtru determinist pentru tot ce pleacă spre internet.

Fail-closed: o denylist lipsă, goală sau cu placeholder-e oprește pornirea;
orice potrivire blochează cererea. Fără LLM, fără excepții, fără override.

Prinde: majuscule/minuscule, diacritice, separatori ("A.c-m e"), leetspeak
simplu ("Acm3"), percent-encoding din URL-uri, chei și valori din JSON imbricat.
Nu prinde: base64 sau alte codificări — cine trimite date spre web trimite text clar.
"""
import os
import re
import unicodedata
from urllib.parse import unquote_plus

import yaml

_LEET = str.maketrans("0134578@$", "oleastbas")
_MIN_COMPACT = 4  # termenii mai scurți se potrivesc doar ca și cuvânt întreg


class EgressBlocked(Exception):
    """Mesajul conține doar ID-urile regulilor, niciodată textul sensibil."""

    def __init__(self, rules):
        self.rules = rules
        super().__init__("egress blocat de regulile: " + ", ".join(rules))


def _norm(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def _compact(s):
    # Fals pozitive posibile ("Hal Stomatologie" conține "alstom") — acceptat: fail-closed.
    return re.sub(r"[\W_]+", "", s.translate(_LEET))


def _strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _strings(v)
    elif obj is not None:
        yield str(obj)


class EgressGuard:
    def __init__(self, terms, patterns=()):
        terms = [t.strip() for t in terms if t and t.strip()]
        if not terms:
            raise ValueError("denylist fără termeni: refuz pornirea")
        if any("<" in t or ">" in t for t in terms):
            raise ValueError("denylist conține placeholder-e necompletate")
        normed = [_norm(t) for t in terms]
        self._words = [re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)") for t in normed]
        self._compacts = [_compact(t) for t in normed]
        self._patterns = [re.compile(p) for p in patterns]

    def violations(self, text):
        """ID-urile regulilor încălcate de text (listă goală = curat)."""
        hits = set()
        for variant in {text, unquote_plus(text)}:
            n = _norm(variant)
            c = _compact(n)
            for i, (word, comp) in enumerate(zip(self._words, self._compacts)):
                if word.search(n) or (len(comp) >= _MIN_COMPACT and comp in c):
                    hits.add(f"term#{i}")
            for i, p in enumerate(self._patterns):
                if p.search(variant) or p.search(n):
                    hits.add(f"pattern#{i}")
        return sorted(hits)

    def check(self, payload):
        """Verifică recursiv str/dict/list (inclusiv cheile). Întoarce payload-ul sau ridică EgressBlocked."""
        hits = sorted({h for s in _strings(payload) for h in self.violations(s)})
        if hits:
            raise EgressBlocked(hits)
        return payload


def load(path=None):
    with open(path or os.environ["DENYLIST_PATH"], encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return EgressGuard(data.get("terms") or [], data.get("patterns") or [])

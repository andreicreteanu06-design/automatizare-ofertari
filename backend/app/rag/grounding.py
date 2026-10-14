"""Post-procesor anti-halucinație pentru răspunsurile Colibri.

Pentru fiecare propoziție (sau rând de listă) din răspuns:
  1. citările [doc_id:pagina] care nu corespund unui fragment primit sunt șterse;
  2. orice cod de piesă din propoziție trebuie să apară (cu aceleași caractere,
     separatorii ' ./-' ignorați) în textul fragmentelor citate ÎN ACEEAȘI propoziție;
     altfel e înlocuit cu „[cod neverificat]”.
Propozițiile fără citare nu pot susține niciun cod. Determinist, fără LLM.
"""
import re
from dataclasses import dataclass, field

NOT_FOUND = "Nu am găsit această informație în documentele interne."
REMOVED = "[cod neverificat]"

_CITE = re.compile(r"\[([A-Za-z0-9_.-]+):(\d+)(?:-\d+)?\]")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]{2,}[A-Za-z0-9]")
_SEGMENT_BREAK = re.compile(r"((?<=[.!?])[ \t]+(?!\[)|\n+)")  # „…EUR. [X:1]” rămâne o propoziție
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def norm_code(s):
    return re.sub(r"[\s./-]", "", s).upper()


def is_part_code(token):
    """Cod de piesă: litere + cifre (3EST000123, M12X40, S355), sau doar cifre lungi
    fără separatori (GTIN). Nu: date (2026-09-15), prețuri (549.00), ani, norme scrise „EN 15085”."""
    n = norm_code(token)
    if token.isdigit():
        return len(token) >= 8
    return len(n) >= 4 and any(c.isdigit() for c in n) and any(c.isalpha() for c in n)


def _code_in(code, text):
    body = "[ ./-]?".join(re.escape(c) for c in norm_code(code))
    return re.search(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", text, re.I) is not None


@dataclass
class Grounded:
    answer: str
    citations: list = field(default_factory=list)          # (doc_id, pagina) valide, în ordine
    removed_codes: list = field(default_factory=list)
    removed_citations: list = field(default_factory=list)

    @property
    def grounded(self):
        return bool(self.citations) or self.answer.strip() == NOT_FOUND


def ground(answer, fragments):
    """fragments: [{"doc_id", "page", "page_end", "text"}] — exact ce a primit modelul."""
    def lookup(doc_id, page):
        return [f["text"] for f in fragments
                if f["doc_id"] == doc_id and f["page"] <= page <= f.get("page_end", f["page"])]

    result = Grounded("")
    out = []
    for seg in _SEGMENT_BREAK.split(_THINK.sub("", answer).strip()):
        if _SEGMENT_BREAK.fullmatch(seg):
            out.append(seg)
            continue
        cited_texts, keep = [], []

        def check_cite(m):
            texts = lookup(m[1], int(m[2]))
            if not texts:
                result.removed_citations.append(m[0])
                return "\x00"  # marcaj șters la final
            cited_texts.extend(texts)
            key = (m[1], int(m[2]))
            if key not in result.citations:
                result.citations.append(key)
            keep.append(m[0])
            return f"\x01{len(keep) - 1}\x01"  # ascunde citarea de scanarea de coduri

        masked = _CITE.sub(check_cite, seg)

        def check_code(m):
            token = m[0]
            if not is_part_code(token) or any(_code_in(token, t) for t in cited_texts):
                return token
            result.removed_codes.append(token)
            return REMOVED

        masked = _TOKEN.sub(check_code, masked)
        masked = re.sub(r"\x01(\d+)\x01", lambda m: keep[int(m[1])], masked)
        out.append(re.sub(r"[ \t]*\x00", "", masked))
    result.answer = "".join(out).strip()
    return result

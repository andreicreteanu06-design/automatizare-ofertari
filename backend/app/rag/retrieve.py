"""Retriever hibrid: ÎNTÂI calea exact-code în Postgres, APOI vectorial în Qdrant.

1. Din interogare se extrag codurile candidate, normalizate exact ca în SQL
   (seller_code_norm): fără spații . / - , majuscule.
2. Exact-code path: price_history după seller_code_norm / buyer_code_norm.
   Acestea sunt fapte (prețuri facturate) și au întotdeauna prioritate.
3. Abia apoi Qdrant, pentru context tehnic suplimentar. Interogarea vectorială e
   îmbogățită cu denumirile articolelor găsite la pasul 2: un cod singur
   („3EST000123”) nu are semantică, „Suport boghiu” are.

Conexiunea Postgres trebuie deschisă cu row_factory=dict_row.
"""
import re
from dataclasses import dataclass

from app.rag.index import vector_search

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./-]{2,}[A-Za-z0-9]")

EXACT_SQL = """
SELECT seller_code, buyer_code, name, supplier, invoice_number, issue_date, currency,
       quantity, unit_code, unit_price, net_unit_price, hs_code, has_doc_allowance
FROM price_history
WHERE seller_code_norm = ANY(%(codes)s) OR buyer_code_norm = ANY(%(codes)s)
ORDER BY issue_date DESC
LIMIT %(limit)s
"""


def norm_code(s):
    return re.sub(r"[\s./-]", "", s).upper()


def _code_like(c):
    # Are cifre și (litere sau e lung, ca un GTIN) — nu „2026” sau „M12”.
    return len(c) >= 4 and any(ch.isdigit() for ch in c) and (any(ch.isalpha() for ch in c) or len(c) >= 6)


def code_candidates(query):
    cands = {norm_code(t) for t in _TOKEN.findall(query)}
    parts = query.split()
    # „3EST 000 123” tastat cu spații = un singur cod; dar „pret 3EST…” nu se lipește.
    if len(parts) > 1 and all(any(ch.isdigit() for ch in p) for p in parts):
        cands.add(norm_code(query))
    return sorted(c for c in cands if _code_like(c))


def exact_lookup(conn, codes, limit=50):
    if not codes:
        return []
    return conn.execute(EXACT_SQL, {"codes": codes, "limit": limit}).fetchall()


@dataclass(frozen=True)
class Retrieval:
    codes: list[str]
    exact: list[dict]      # rânduri price_history — fapte, prioritare
    context: list[dict]    # chunk-uri Qdrant, fiecare cu "cite": "[doc_id:pagina]"
    rerank_status: str = 'disabled'


def retrieve(query, *, conn, qdrant, embedder, k=5):
    codes = code_candidates(query)
    exact = exact_lookup(conn, codes)                                   # 1. exact-code path
    names = list(dict.fromkeys(r["name"] for r in exact if r.get("name")))[:3]
    from app.rag.rerank import enabled, rerank
    use_rerank = enabled()
    context = vector_search(qdrant, embedder, " ".join([query, *names]), min(30, k * 3) if use_rerank else k)
    status = 'disabled'
    if use_rerank:
        context, status = rerank(query, context, k)
    return Retrieval(codes, exact, context, status)

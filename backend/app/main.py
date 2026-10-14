"""Backend API. POST /chat: retriever hibrid -> Colibri -> post-procesor anti-halucinație."""
import os
import re
from decimal import Decimal
from functools import lru_cache

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.llm import Colibri, build_messages
from app.quoting import compliance, export
from app.quoting.email import router as email_router
from app.quoting.engine import FxError, calc_offer
from app.quoting.models import Offer
from app.quoting.saga import SagaExportIn, build_xml, client_cif_ok, company_from_env
from app.rag.grounding import NOT_FOUND, ground

MAX_CONTEXT_CHARS = 12_000  # ~3.5k tokeni: promptul încape în KV-cache-ul Colibri pe 16 GB

app = FastAPI(title="ofertare-backend")
app.include_router(email_router)


def invoice_fragments(rows):
    """Rândurile price_history devin fragmente citabile [FACT-<nr>:1], grupate pe factură."""
    grouped = {}
    for r in rows:
        doc_id = "FACT-" + (re.sub(r"[^A-Za-z0-9_-]+", "-", r["invoice_number"]).strip("-") or "x")
        line = (f"Cod furnizor: {r['seller_code'] or '-'}; Cod intern: {r['buyer_code'] or '-'}; "
                f"Articol: {r['name']}; Data: {r['issue_date']}; Cantitate: {r['quantity']} {r['unit_code'] or ''}; "
                f"Preț unitar listă: {r['unit_price']} {r['currency']}; "
                f"Preț unitar net: {r['net_unit_price']} {r['currency']}; Cod vamal: {r['hs_code'] or '-'}"
                + ("; factura are și o reducere la nivel de document" if r.get("has_doc_allowance") else ""))
        f = grouped.setdefault(doc_id, {
            "doc_id": doc_id, "page": 1, "page_end": 1, "supplier": r["supplier"], "doc_type": "Factură",
            "text": f"[Furnizor: {r['supplier']} | Producător: necunoscut | Doc: Factură {r['invoice_number']}"
                    f" | Pagina 1]"})
        f["text"] += "\n" + line
    return list(grouped.values())


def build_fragments(retrieval, max_chars=MAX_CONTEXT_CHARS):
    """Faptele din facturi întâi, apoi chunk-urile Qdrant, până la bugetul de context."""
    chunks = [{"doc_id": c["doc_id"], "page": c["page"], "page_end": c.get("page_end", c["page"]),
               "supplier": c.get("supplier"), "doc_type": c.get("doc_type"), "text": c["text"]}
              for c in retrieval.context]
    out, used = [], 0
    for f in invoice_fragments(retrieval.exact) + chunks:
        if out and used + len(f["text"]) > max_chars:
            break
        out.append(f)
        used += len(f["text"])
    return out


# --- Dependențe (înlocuite în teste prin app.dependency_overrides) ------------------

@lru_cache
def _qdrant():
    from app.rag.index import qdrant_client
    return qdrant_client()


@lru_cache
def _embedder():
    from app.rag.index import BgeM3
    return BgeM3()  # ~2.3 GB; încărcat la prima întrebare, apoi refolosit


def get_retriever():
    def run(query, k):
        import psycopg
        from psycopg.rows import dict_row

        from app.rag.retrieve import retrieve
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
            return retrieve(query, conn=conn, qdrant=_qdrant(), embedder=_embedder(), k=k)
    return run


@lru_cache
def get_llm():
    return Colibri()


# --- Endpoint-uri -------------------------------------------------------------------

class ChatIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int = Field(5, ge=1, le=10)


@app.post("/chat")
async def chat(body: ChatIn, retriever=Depends(get_retriever), llm=Depends(get_llm)):
    retrieval = await run_in_threadpool(retriever, body.query, body.k)
    fragments = build_fragments(retrieval)
    if not fragments:  # nimic de citat: nu pierdem minute de CPU pe Colibri
        return {"answer": NOT_FOUND, "grounded": True, "citations": [], "removed_codes": [],
                "removed_citations": [], "codes": retrieval.codes, "exact": []}
    try:
        raw = await llm.complete(build_messages(body.query, fragments))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Colibri indisponibil: {type(e).__name__}") from None
    g = ground(raw, fragments)
    by_key = {(f["doc_id"], f["page"]): f for f in fragments}
    return {
        "answer": g.answer,
        "grounded": g.grounded,
        "citations": [{"cite": f"[{d}:{p}]", "doc_id": d, "page": p,
                       "supplier": by_key.get((d, p), {}).get("supplier"),
                       "doc_type": by_key.get((d, p), {}).get("doc_type")} for d, p in g.citations],
        "removed_codes": g.removed_codes,
        "removed_citations": g.removed_citations,
        "codes": retrieval.codes,
        "exact": [_money_safe(r) for r in retrieval.exact],  # faptele din facturi, pentru UI
    }


def _money_safe(row):
    # FastAPI ar face Decimal -> float (549.000000 -> 549.0, 0.1 -> 0.1000000000000000055...).
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}


@app.get("/health")
def health():
    return {"ok": True}


def get_price_lookup():
    def run(code):
        import psycopg
        from psycopg.rows import dict_row

        from app.rag.retrieve import code_candidates, exact_lookup, norm_code
        codes = code_candidates(code) or [norm_code(code)]
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
            return exact_lookup(conn, codes, limit=10)
    return run


@app.get("/prices")
async def prices(code: str = Query(min_length=2, max_length=64), lookup=Depends(get_price_lookup)):
    """Istoricul de achiziție pentru un cod (cele mai recente întâi) — precompletează oferta."""
    rows = await run_in_threadpool(lookup, code)
    return {"code": code, "history": [_money_safe(r) for r in rows]}


# --- Ofertare (Faza 3) ---------------------------------------------------------------

def get_fx():
    from app.quoting.fx import bnr_snapshot
    return bnr_snapshot


async def _calculate(offer, fx_source):
    try:
        fx = await fx_source(offer.fx_date or offer.offer_date)
        return calc_offer(offer, fx)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"curs BNR indisponibil prin research-gateway: {type(e).__name__}") from None
    except FxError as e:
        raise HTTPException(422, str(e)) from None


def _calc_json(calc, failures):
    return {
        "fx": {"source": "BNR", "date": calc.fx.date.isoformat(), "eur_ron": str(calc.fx.rate("EUR"))},
        "lines": [{"code": c.line.code, "price_eur": str(c.price_eur), "transport_eur": str(c.transport_eur),
                   "duty_eur": str(c.duty_eur), "landed_eur": str(c.landed_eur),
                   "sale_unit_eur": str(c.sale_unit_eur), "sale_total_eur": str(c.sale_total_eur),
                   "margin_eur": str(c.margin_eur)} for c in calc.lines],
        "total_landed_eur": str(calc.total_landed_eur),
        "total_sale_eur": str(calc.total_sale_eur),
        "total_margin_eur": str(calc.total_margin_eur),
        "margin_on_sale_percent": str(calc.margin_on_sale_percent),
        "compliance": {"ok": not failures, "failures": [vars(f) for f in failures]},
    }


@app.post("/offers/calculate")
async def offers_calculate(offer: Offer, fx_source=Depends(get_fx)):
    """Calcul intern + starea checklist-ului (neblocant): pentru pregătirea ofertei."""
    return _calc_json(await _calculate(offer, fx_source), compliance.check(offer))


def _safe_name(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "oferta"


async def _export(offer, fx_source, kind):
    failures = compliance.check(offer)  # ÎNAINTE de orice calcul sau generare
    if failures:
        raise HTTPException(409, {"error": "checklist de conformitate nevalidat — export refuzat",
                                  "failures": [vars(f) for f in failures]})
    calc = await _calculate(offer, fx_source)
    name = _safe_name(offer.offer_number)
    if kind == "xlsx":
        data, mime, filename = export.excel(offer, calc), XLSX_MIME, f"calcul_intern_{name}.xlsx"
    else:
        data, mime, filename = export.word(offer, calc), DOCX_MIME, f"oferta_{name}.docx"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@app.post("/offers/export/xlsx")
async def offers_export_xlsx(offer: Offer, fx_source=Depends(get_fx)):
    return await _export(offer, fx_source, "xlsx")


@app.post("/offers/export/docx")
async def offers_export_docx(offer: Offer, fx_source=Depends(get_fx)):
    return await _export(offer, fx_source, "docx")


@app.post("/offers/export/saga")
async def offers_export_saga(req: SagaExportIn, fx_source=Depends(get_fx)):
    """XML pentru importul Saga la Ieșiri; prețuri în RON la cursul BNR al ofertei."""
    failures = compliance.check(req)
    if failures:
        raise HTTPException(409, {"error": "checklist de conformitate nevalidat — export refuzat",
                                  "failures": [vars(f) for f in failures]})
    if not client_cif_ok(req.client_cif):
        raise HTTPException(422, f"CUI client invalid (cifra de control / format): {req.client_cif}")
    company = company_from_env()
    if not company:
        raise HTTPException(503, "configurează COMPANY_CIF / COMPANY_NAME în .env — Saga rutează la Ieșiri după CIF")
    name, data = build_xml(req, await _calculate(req, fx_source), company)
    return Response(data, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{name}"'})

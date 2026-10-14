import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from app.ingest import watch

FIX = Path(__file__).parent / "fixtures" / "synthetic"


def put(inbox, folder, name, data=b"x", age=60):
    p = inbox / folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    t = time.time() - age
    os.utime(p, (t, t))
    return p


class Handlers:
    def __init__(self, fail=()):
        self.invoices, self.pdfs, self.fail = [], [], set(fail)

    def invoice(self, path):
        self.invoices.append(path.name)
        if path.name in self.fail:
            raise ValueError("lipsește CUI furnizor")
        return "1 facturi noi, 0 existente"

    def pdf(self, path, supplier):
        self.pdfs.append((path.name, supplier))
        if path.name in self.fail:
            raise RuntimeError("Docling: PDF criptat")
        return "3 chunk-uri indexate"


def scan(inbox, h, min_age=10):
    return asyncio.run(watch.scan_once(inbox, h.invoice, h.pdf, min_age))


def test_routes_by_folder_and_moves_to_processed(tmp_path):
    put(tmp_path, "invoices", "a_factura.xml")
    put(tmp_path, "invoices", "b_spv.zip")
    put(tmp_path, "tech", "c_fisa.pdf")
    h = Handlers()
    done = scan(tmp_path, h)
    assert sorted(h.invoices) == ["a_factura.xml", "b_spv.zip"]
    assert h.pdfs == [("c_fisa.pdf", "necunoscut")]
    assert {s for _, s, _ in done} == {"processed"}
    assert sorted(p.name for p in (tmp_path / "invoices" / "processed").iterdir()) == ["a_factura.xml", "b_spv.zip"]
    assert scan(tmp_path, h) == []  # deja procesate: nimic de făcut


def test_failure_moves_to_failed_with_reason(tmp_path):
    put(tmp_path, "invoices", "rea.xml")
    put(tmp_path, "invoices", "buna.xml")
    done = scan(tmp_path, Handlers(fail={"rea.xml"}))
    assert ("rea.xml", "failed", "ValueError: lipsește CUI furnizor") in done
    assert ("buna.xml", "processed", "1 facturi noi, 0 existente") in done  # eșecul nu oprește restul
    assert (tmp_path / "invoices" / "failed" / "rea.xml.error.txt").read_text("utf-8") == "ValueError: lipsește CUI furnizor"


def test_skips_fresh_partial_and_foreign_files(tmp_path):
    put(tmp_path, "invoices", "proaspat.xml", age=2)          # încă se copiază
    put(tmp_path, "invoices", "x.xml.part")                   # scriere atomică în curs
    put(tmp_path, "invoices", ".ascuns.xml")
    put(tmp_path, "tech", "lista.xlsx")                       # nu e PDF
    put(tmp_path, "invoices", "fisa.pdf")                     # PDF în folderul de facturi
    h = Handlers()
    assert scan(tmp_path, h) == [] and h.invoices == h.pdfs == []


def test_missing_folders_are_fine(tmp_path):
    assert scan(tmp_path, Handlers()) == []


def test_supplier_from_mail_log(tmp_path):
    put(tmp_path, "tech", "abc_fisa.pdf")
    (tmp_path / "_mail_log.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"file": "tech/alt.pdf", "from": "x@alt.ro"},
        {"file": "tech/abc_fisa.pdf", "from": "vanzari@feroparts.ro"},
    ]), encoding="utf-8")
    h = Handlers()
    scan(tmp_path, h)
    assert h.pdfs == [("abc_fisa.pdf", "feroparts.ro")]


def test_real_invoice_handler_parses_before_db(tmp_path, monkeypatch):
    """Handler-ul real respinge un XML invalid înainte de orice conexiune la DB."""
    import psycopg

    def no_db(*a, **k):
        raise AssertionError("nu trebuia să ajungă la DB")
    monkeypatch.setattr(psycopg, "connect", no_db)
    p = put(tmp_path, "invoices", "rea.xml", b"<Order xmlns='urn:x'/>")
    with pytest.raises(Exception, match="nu e factură"):
        watch.ingest_invoice(p)


def test_pdf_handler_runs_docling_as_subprocess(tmp_path, monkeypatch):
    calls = []

    class R:
        returncode, stdout, stderr = 0, "doc: 5 chunk-uri (2 tabele) indexate\n", ""
    monkeypatch.setattr(watch.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or R())
    assert watch.ingest_pdf(tmp_path / "f.pdf", "feroparts.ro") == "doc: 5 chunk-uri (2 tabele) indexate"
    cmd, kw = calls[0]
    assert cmd[1:3] == ["-m", "app.ingest.pdf"] and cmd[cmd.index("--supplier") + 1] == "feroparts.ro"
    assert kw["timeout"] == watch.PDF_TIMEOUT


def test_pdf_handler_failure_surfaces_stderr(tmp_path, monkeypatch):
    class R:
        returncode, stdout, stderr = 1, "", "Traceback...\nConversionError: PDF criptat"
    monkeypatch.setattr(watch.subprocess, "run", lambda cmd, **kw: R())
    with pytest.raises(RuntimeError, match="PDF criptat"):
        watch.ingest_pdf(tmp_path / "f.pdf", "x")

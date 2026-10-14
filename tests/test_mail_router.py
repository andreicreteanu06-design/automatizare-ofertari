"""mail_router: IMAP mock-uit (aceeași formă de răspuns ca imaplib), Laya mock-uit."""
import asyncio
import imaplib
import io
import json
import zipfile
from email import message_from_bytes
from email.message import EmailMessage
from pathlib import Path

import httpx
import pytest
from openpyxl import Workbook

from mail_router import classify, fetch

FIX = Path(__file__).parent / "fixtures" / "synthetic"
UBL = (FIX / "factura_eur.xml").read_bytes()


# --- IMAP fals -----------------------------------------------------------------------

class FakeIMAP:
    def __init__(self, messages, select_ok=True):
        self.messages = {str(i).encode(): m for i, m in enumerate(messages, 1)}
        self.seen, self.calls, self.select_ok = set(), [], select_ok

    def select(self, folder):
        self.calls.append(("SELECT", folder))
        return ("OK" if self.select_ok else "NO"), [b"1"]

    def uid(self, cmd, *args):
        self.calls.append((cmd, *args))
        if cmd == "SEARCH":
            return "OK", [b" ".join(u for u in self.messages if u not in self.seen)]
        if cmd == "FETCH":
            raw = self.messages[args[0]]
            return "OK", [(b"1 (UID " + args[0] + b" BODY[] {%d}" % len(raw), raw), b")"]
        if cmd == "STORE":
            self.seen.add(args[0])
            return "OK", [b"1 (FLAGS (\\Seen))"]
        raise AssertionError(cmd)


def mail(*attachments, sender="facturi@furnizor.ro", subject="Documente comanda 4512"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = f"Furnizor <{sender}>", "achizitii@firma.ro", subject
    m["Message-ID"] = "<abc@furnizor.ro>"
    m.set_content("Buna ziua, atasat documentele.")
    for name, data, mime in attachments:
        maintype, subtype = mime.split("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()


PDF = ("datasheet.pdf", b"%PDF-1.4 fake", "application/pdf")
XML = ("factura.xml", UBL, "application/xml")


def files(d):
    return sorted(p.name for p in d.iterdir() if p.is_file())


# --- mail-fetch ----------------------------------------------------------------------

def test_saves_attachments_with_sidecar_and_marks_seen(tmp_path):
    imap = FakeIMAP([mail(PDF, XML)])
    stats = fetch.poll_once(imap, tmp_path)
    assert stats == {"messages": 1, "saved": 2, "skipped": 0}
    names = files(tmp_path)
    assert len(names) == 4 and sum(n.endswith(".json") for n in names) == 2
    pdf = next(p for p in tmp_path.glob("*_datasheet.pdf"))
    assert pdf.read_bytes() == PDF[1]
    meta = json.loads(Path(str(pdf) + ".json").read_text("utf-8"))
    assert (meta["original_name"], meta["from"], meta["subject"]) == (
        "datasheet.pdf", "facturi@furnizor.ro", "Documente comanda 4512")
    assert imap.seen == {b"1"}
    assert ("FETCH", b"1", "(BODY.PEEK[])") in imap.calls  # nu marchează citit la descărcare


def test_second_poll_is_noop(tmp_path):
    imap = FakeIMAP([mail(PDF)])
    fetch.poll_once(imap, tmp_path)
    assert fetch.poll_once(imap, tmp_path) == {"messages": 0, "saved": 0, "skipped": 0}


@pytest.mark.parametrize("att", [("virus.exe", b"MZ", "application/octet-stream"),
                                 ("macro.docm", b"PK", "application/octet-stream"),
                                 ("fara_extensie", b"x", "application/octet-stream"),
                                 ("gol.pdf", b"", "application/pdf")])
def test_rejected_attachments(tmp_path, att):
    imap = FakeIMAP([mail(att)])
    assert fetch.poll_once(imap, tmp_path)["skipped"] == 1
    assert files(tmp_path) == [] and imap.seen == {b"1"}


def test_oversized_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "MAX_BYTES", 10)
    assert fetch.poll_once(FakeIMAP([mail(("mare.pdf", b"x" * 11, "application/pdf"))]), tmp_path)["skipped"] == 1


@pytest.mark.parametrize("evil", ["../../etc/cron.d/x.pdf", "..\\..\\Windows\\x.pdf", "/abs/x.pdf", "..pdf.pdf"])
def test_path_traversal_neutralized(tmp_path, evil):
    q = tmp_path / "q"
    q.mkdir()
    fetch.poll_once(FakeIMAP([mail((evil, b"%PDF", "application/pdf"))]), q)
    assert all(p.parent == q for p in tmp_path.rglob("*") if p.is_file())
    assert not any(".." in n for n in files(q))


def test_write_failure_leaves_message_unseen_for_retry(tmp_path, monkeypatch):
    imap = FakeIMAP([mail(PDF)])
    real_save = fetch.save
    monkeypatch.setattr(fetch, "save", lambda *a: (_ for _ in ()).throw(OSError("disc plin")))
    with pytest.raises(OSError):
        fetch.poll_once(imap, tmp_path)
    assert imap.seen == set()
    monkeypatch.setattr(fetch, "save", real_save)
    assert fetch.poll_once(imap, tmp_path)["saved"] == 1  # reluat la ciclul următor


def test_same_content_twice_is_one_file(tmp_path):
    fetch.poll_once(FakeIMAP([mail(PDF), mail(PDF)]), tmp_path)
    assert len(list(tmp_path.glob("*_datasheet.pdf"))) == 1


def test_sender_domain_allowlist(tmp_path):
    imap = FakeIMAP([mail(PDF, sender="x@spam.example"), mail(XML, sender="a@eu.furnizor.ro")])
    stats = fetch.poll_once(imap, tmp_path, allowed_domains=["furnizor.ro"])
    assert stats["saved"] == 1 and len(list(tmp_path.glob("*_factura.xml"))) == 1
    assert imap.seen == {b"1", b"2"}  # cel respins nu e reluat la nesfârșit


def test_forwarded_message_attachments(tmp_path):
    outer = EmailMessage()
    outer["From"], outer["Subject"] = "coleg@firma.ro", "Fwd: factura"
    outer.set_content("vezi mai jos")
    outer.add_attachment(message_from_bytes(mail(XML)), filename="original.eml")  # message/rfc822
    fetch.poll_once(FakeIMAP([outer.as_bytes()]), tmp_path)
    assert len(list(tmp_path.glob("*_factura.xml"))) == 1


def test_select_failure_raises(tmp_path):
    with pytest.raises(imaplib.IMAP4.error):
        fetch.poll_once(FakeIMAP([], select_ok=False), tmp_path)


def test_main_requires_credentials(monkeypatch):
    for v in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(SystemExit, match="IMAP_HOST, IMAP_USER, IMAP_PASSWORD"):
        fetch.main()


# --- mail-classify -------------------------------------------------------------------

class FakeLaya:
    def __init__(self, label="datasheet", p=0.95, exc=None):
        self.label, self.p, self.exc, self.states = label, p, exc, []

    async def __call__(self, state):
        self.states.append(state)
        if self.exc:
            raise self.exc
        return self.label, self.p


def quarantine_with(tmp_path, *attachments, subject="Documente comanda 4512"):
    q, inbox = tmp_path / "q", tmp_path / "inbox"
    q.mkdir()
    fetch.poll_once(FakeIMAP([mail(*attachments, subject=subject)]), q)  # perechi reale, scrise de fetch
    return q, inbox


def run(q, inbox, laya):
    return asyncio.run(classify.process_once(q, inbox, laya))


def anaf_zip(with_invoice=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if with_invoice:
            z.writestr("4567.xml", UBL)
        z.writestr("semnatura_4567.xml", "<Signature/>")
    return buf.getvalue()


@pytest.mark.parametrize("att,folder", [
    (XML, "invoices"),
    (("nota.xml", b"<Order xmlns='urn:x'/>", "application/xml"), "unsorted"),
    (("4567.zip", anaf_zip(), "application/zip"), "invoices"),
    (("arhiva.zip", anaf_zip(False), "application/zip"), "unsorted"),
    (("stricat.zip", b"PK\x03\x04 nu e zip", "application/zip"), "unsorted"),
])
def test_deterministic_routing_without_laya(tmp_path, att, folder):
    q, inbox = quarantine_with(tmp_path, att)
    laya = FakeLaya()
    (moved,) = run(q, inbox, laya)
    assert moved[1] == folder and laya.states == []
    assert files(q) == []  # carantina golită


@pytest.mark.parametrize("label,p,folder", [
    ("datasheet", 0.95, "tech"), ("price_list", 0.8, "pricelists"),
    ("datasheet", 0.5, "unsorted"),       # sub prag -> revizuire manuală
    ("invoice", 0.99, "unsorted"),        # factură PDF: parserul e-Factura cere XML
    ("other", 0.99, "unsorted"),
])
def test_laya_routing(tmp_path, label, p, folder):
    q, inbox = quarantine_with(tmp_path, PDF)
    (moved,) = run(q, inbox, FakeLaya(label, p))
    assert moved[1] == folder
    assert (inbox / folder / moved[0]).read_bytes() == PDF[1]


def test_laya_state_has_name_subject_and_content(tmp_path):
    csv = ("lista_preturi_2026.csv", "Cod;Pret unitar EUR\n3EST000123;555\n".encode(), "text/csv")
    q, inbox = quarantine_with(tmp_path, csv, subject="Price list Q4")
    laya = FakeLaya("price_list", 0.9)
    run(q, inbox, laya)
    (state,) = laya.states
    assert "File name: lista_preturi_2026.csv" in state and "E-mail subject: Price list Q4" in state
    assert "3EST000123;555" in state and len(state) <= classify.STATE_CHARS


def test_xlsx_content_reaches_laya(tmp_path):
    wb = Workbook()
    wb.active.append(["Article", "Unit price", "Currency"])
    wb.active.append(["3EST000123", 555, "EUR"])
    buf = io.BytesIO()
    wb.save(buf)
    q, inbox = quarantine_with(tmp_path, ("preise.xlsx", buf.getvalue(), "application/vnd.ms-excel"))
    laya = FakeLaya("price_list", 0.9)
    assert run(q, inbox, laya)[0][1] == "pricelists"
    assert "Article | Unit price | Currency" in laya.states[0]


def test_garbage_pdf_does_not_crash(tmp_path):
    assert classify.content_text("x.pdf", b"%PDF-1.7 \x00\xff garbage") == ""


def test_laya_down_keeps_file_in_quarantine_then_retries(tmp_path):
    q, inbox = quarantine_with(tmp_path, PDF)
    assert run(q, inbox, FakeLaya(exc=httpx.ConnectError("laya down"))) == []
    assert len(files(q)) == 2  # fișier + sidecar, neatinse
    assert run(q, inbox, FakeLaya("datasheet", 0.9))[0][1] == "tech"


def test_incomplete_pair_is_ignored(tmp_path):
    q, inbox = tmp_path / "q", tmp_path / "inbox"
    q.mkdir()
    (q / "abc_x.pdf").write_bytes(b"%PDF")          # fișier fără sidecar (încă în scriere)
    (q / "def_y.pdf.json").write_text("{}")          # sidecar fără fișier
    assert run(q, inbox, FakeLaya()) == []


def test_audit_log(tmp_path):
    q, inbox = quarantine_with(tmp_path, XML)
    run(q, inbox, FakeLaya())
    (entry,) = [json.loads(line) for line in (inbox / "_mail_log.jsonl").read_text("utf-8").splitlines()]
    assert entry["label"] == "invoice" and entry["file"].startswith("invoices/")
    assert entry["from"] == "facturi@furnizor.ro"


def test_laya_classify_request_and_response():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"answers": {"doc_type": {
            "type": "choice", "choice": "price_list", "confidence": 0.7,
            "probabilities": {"invoice": 0.02, "datasheet": 0.05, "price_list": 0.91, "other": 0.02}}}})
    label, p = asyncio.run(classify.laya_classify("state", url="http://laya:5000/v1/systemone",
                                                  transport=httpx.MockTransport(handler)))
    assert (label, p) == ("price_list", 0.91)
    assert seen[0]["model"] == "laya" and seen[0]["questions"]["doc_type"]["type"] == "choice"


def test_end_to_end_inbox_layout(tmp_path):
    q, inbox = quarantine_with(tmp_path, XML, PDF, ("4567.zip", anaf_zip(), "application/zip"))
    run(q, inbox, FakeLaya("datasheet", 0.9))
    assert {p.parent.name for p in inbox.rglob("*") if p.is_file() and p.suffix != ".jsonl"} == {"invoices", "tech"}
    assert len(list((inbox / "invoices").iterdir())) == 2

"""Ingestie automată: data/inbox/invoices -> e-Factura (Postgres), data/inbox/tech -> Docling (Qdrant).

Polling, nu inotify: evenimentele de fișiere nu traversează sigur bind-mount-urile
Docker Desktop de pe Windows. Un fișier e preluat doar dacă:
  - nu e temporar (.part) și are extensia potrivită folderului;
  - nu s-a mai modificat de MIN_AGE secunde (copiat complet, inclusiv manual).
După procesare: <folder>/processed/ sau <folder>/failed/ (+ <nume>.error.txt cu motivul).
Docling rulează ca SUBPROCES per PDF: modelele (~2-4 GB) se eliberează după fiecare document.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("ingest-watch")

FOLDERS = {"invoices": {".xml", ".zip"}, "tech": {".pdf"}}
MIN_AGE = float(os.environ.get("INGEST_MIN_AGE_SECONDS", "10"))
PDF_TIMEOUT = 1800  # 30 min: Docling ACCURATE pe CPU, PDF-uri lungi


def ready_files(folder, extensions, min_age=MIN_AGE, now=None):
    now = now or time.time()
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in extensions and not p.name.startswith(".")
                  and now - p.stat().st_mtime >= min_age)


def _move(path, sub, error=None):
    dest_dir = path.parent / sub
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), dest)
    if error:
        (dest_dir / f"{path.name}.error.txt").write_text(error, encoding="utf-8")
    return dest


def mail_meta(inbox, folder, name):
    """Intrarea din _mail_log.jsonl (scris de mail-classify) pentru fișier, dacă există."""
    logf = inbox / "_mail_log.jsonl"
    if logf.exists():
        for line in reversed(logf.read_text("utf-8").splitlines()):
            entry = json.loads(line)
            if entry.get("file") == f"{folder}/{name}":
                return entry
    return {}


def supplier_from_mail(meta):
    # shortcut: furnizorul = domeniul expeditorului; upgrade: tabel domeniu -> nume furnizor.
    addr = meta.get("from") or ""
    return addr.rpartition("@")[2] or "necunoscut"


def ingest_invoice(path):
    import psycopg

    from app.ingest.efactura import read_file, store
    invoices = read_file(path)  # validare completă ÎNAINTE de a deschide conexiunea la DB
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        ids = [store(conn, inv) for inv in invoices]
    return f"{sum(i is not None for i in ids)} facturi noi, {sum(i is None for i in ids)} existente"


def ingest_pdf(path, supplier):
    r = subprocess.run([sys.executable, "-m", "app.ingest.pdf", str(path), "--supplier", supplier,
                        "--doc-type", "Fișă tehnică"],
                       capture_output=True, text=True, timeout=PDF_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-2000:])
    return r.stdout.strip()


async def scan_once(inbox, invoice_handler=ingest_invoice, pdf_handler=ingest_pdf, min_age=MIN_AGE):
    """Un ciclu. Întoarce [(fișier, 'processed'|'failed', mesaj)]. Handler-ele rulează în thread."""
    done = []
    for folder, extensions in FOLDERS.items():
        for path in ready_files(inbox / folder, extensions, min_age):
            try:
                if folder == "invoices":
                    msg = await asyncio.to_thread(invoice_handler, path)
                else:
                    supplier = supplier_from_mail(mail_meta(inbox, folder, path.name))
                    msg = await asyncio.to_thread(pdf_handler, path, supplier)
                _move(path, "processed")
                done.append((path.name, "processed", msg))
            except Exception as e:  # noqa: BLE001 — un fișier stricat nu oprește restul
                err = f"{type(e).__name__}: {e}"
                _move(path, "failed", err)
                done.append((path.name, "failed", err))
    return done


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    inbox = Path(os.environ.get("INBOX_DIR", "/data/inbox"))
    interval = float(os.environ.get("INGEST_POLL_SECONDS", "30"))
    log.info("monitorizez %s/{%s} la %ss", inbox, ",".join(FOLDERS), interval)
    while True:
        for name, status, msg in asyncio.run(scan_once(inbox)):
            log.info("%s -> %s: %s", name, status, msg)
        time.sleep(interval)


if __name__ == "__main__":
    main()

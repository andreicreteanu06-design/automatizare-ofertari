"""mail-fetch: IMAP -> director de carantină. Rulează DOAR pe rețeaua egress.

Nu are acces la rețeaua internă și nu montează nimic intern în afară de carantină:
dacă un mesaj malițios l-ar compromite, nu are ce exfiltra. Nu parsează conținutul
atașamentelor (asta face mail-classify, care nu are internet).

Garanții:
  - mesajul e marcat \\Seen DOAR după ce toate atașamentele lui au fost scrise pe disc
    (o cădere la mijloc => mesajul e reluat la următorul ciclu; numele pe hash => fără duplicate);
  - fișierul apare atomic (.part -> rename), iar fișierul-sidecar .json e scris ULTIMUL:
    mail-classify procesează doar perechi complete;
  - numele de fișier sunt sanitizate (fără ../), extensiile filtrate, mărimea limitată.
"""
import email
import hashlib
import imaplib
import json
import logging
import os
import re
import ssl
import time
from datetime import datetime, timezone
from email import policy
from email.utils import parseaddr
from pathlib import Path

log = logging.getLogger("mail-fetch")

ALLOWED_EXT = {".xml", ".zip", ".pdf", ".xlsx", ".xls", ".csv"}
MAX_BYTES = 25 * 2**20


def safe_name(name):
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return base[-120:] or "atasament"


def attachments(msg):
    """(nume, content-type, bytes) pentru fiecare atașament, inclusiv din mesaje redirecționate."""
    for part in msg.walk():
        name = part.get_filename()
        if name and not part.is_multipart() and part.get_content_disposition() in ("attachment", "inline"):
            yield name, part.get_content_type(), part.get_payload(decode=True) or b""


def _atomic_write(path, data):
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def save(quarantine, msg, name, ctype, data):
    """Scrie atașamentul + sidecar-ul. Întoarce calea sau motivul respingerii (str)."""
    clean = safe_name(name)
    ext = Path(clean).suffix.lower()
    if ext not in ALLOWED_EXT:
        return f"extensie nepermisă: {ext or '-'}"
    if not data:
        return "atașament gol"
    if len(data) > MAX_BYTES:
        return f"prea mare: {len(data)} B"
    digest = hashlib.sha256(data).hexdigest()
    path = quarantine / f"{digest[:16]}_{clean}"
    _atomic_write(path, data)
    meta = {"original_name": name, "content_type": ctype, "size": len(data), "sha256": digest,
            "from": parseaddr(str(msg.get("From", "")))[1], "subject": str(msg.get("Subject", ""))[:300],
            "date": str(msg.get("Date", "")), "message_id": str(msg.get("Message-ID", "")),
            "received_at": datetime.now(timezone.utc).isoformat()}
    _atomic_write(path.with_name(path.name + ".json"), json.dumps(meta, ensure_ascii=False).encode())
    return path


def sender_allowed(msg, allowed_domains):
    if not allowed_domains:
        return True
    addr = parseaddr(str(msg.get("From", "")))[1].lower()
    domain = addr.rpartition("@")[2]
    return any(domain == d or domain.endswith("." + d) for d in allowed_domains)


def poll_once(imap, quarantine, folder="INBOX", allowed_domains=()):
    """Un ciclu: toate mesajele necitite din `folder`. Întoarce statistici."""
    stats = {"messages": 0, "saved": 0, "skipped": 0}
    typ, _ = imap.select(folder)
    if typ != "OK":
        raise imaplib.IMAP4.error(f"nu pot selecta {folder}")
    typ, data = imap.uid("SEARCH", None, "UNSEEN")
    for uid in (data[0] or b"").split():
        typ, parts = imap.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK: nu marca citit încă
        raw = next((p[1] for p in parts or [] if isinstance(p, tuple)), None)
        if typ != "OK" or raw is None:
            log.warning("nu pot descărca mesajul %s", uid)
            continue
        msg = email.message_from_bytes(raw, policy=policy.default)
        stats["messages"] += 1
        if sender_allowed(msg, allowed_domains):
            for name, ctype, payload in attachments(msg):
                result = save(quarantine, msg, name, ctype, payload)
                if isinstance(result, Path):
                    stats["saved"] += 1
                else:
                    stats["skipped"] += 1
                    log.info("atașament ignorat (%s): %s", result, safe_name(name))
        else:
            log.info("expeditor în afara listei permise: mesaj %s ignorat", uid)
        imap.uid("STORE", uid, "+FLAGS", "(\\Seen)")  # abia acum, după ce totul e pe disc
    return stats


def connect(host, port, user, password):
    imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())  # verifică certificatul
    imap.login(user, password)
    return imap


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    missing = [v for v in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD") if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"mail-fetch: lipsesc variabilele {', '.join(missing)} în .env")
    quarantine = Path(os.environ.get("MAIL_QUARANTINE", "/quarantine"))
    quarantine.mkdir(parents=True, exist_ok=True)
    domains = [d.strip().lower() for d in os.environ.get("IMAP_ALLOWED_SENDER_DOMAINS", "").split(",") if d.strip()]
    interval = int(os.environ.get("IMAP_POLL_SECONDS", "120"))
    while True:
        try:
            imap = connect(os.environ["IMAP_HOST"], int(os.environ.get("IMAP_PORT", "993")),
                           os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
            try:
                log.info("ciclu: %s", poll_once(imap, quarantine, os.environ.get("IMAP_FOLDER", "INBOX"), domains))
            finally:
                imap.logout()
        except (imaplib.IMAP4.error, OSError) as e:
            log.error("IMAP: %s: %s", type(e).__name__, e)  # fără parolă în log
        time.sleep(interval)


if __name__ == "__main__":
    main()

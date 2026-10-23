"""Local OAuth setup, using only Python's standard library. Never prints secrets."""
import argparse
import base64
import getpass
import os
from pathlib import Path
import re
import secrets
import shlex
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=')


def read_env(text):
    values = {}
    for line in text.splitlines():
        match = ASSIGNMENT.match(line)
        if match:
            parts = shlex.split(line[match.end():], comments=True)
            values[match[1]] = ' '.join(parts).replace('$$', '$')
    return values


def validate_public(public):
    try:
        p = urlsplit(public)
        if (p.hostname and p.port != 0 and not any(c.isspace() for c in public)
                and (p.scheme == 'https' or p.scheme == 'http' and p.hostname in ('localhost', '127.0.0.1'))
                and not (p.path or p.query or p.fragment or p.username or p.password)):
            return
    except ValueError:
        pass
    raise ValueError('Adresa aplicației trebuie să fie o origine HTTPS sau http://127.0.0.1:8080 / http://localhost:8080.')


def changes(values, provider, client_id, client_secret, public, tenant='common'):
    validate_public(public)
    if not client_id.strip() or not client_secret.strip():
        raise ValueError('Client ID și Client Secret sunt obligatorii.')
    if any(any(c in value for c in '\r\n\x00') for value in (client_id, client_secret, public, tenant)):
        raise ValueError('Valorile trebuie să fie pe o singură linie.')
    prefix = provider.upper()
    result = {prefix + '_CLIENT_ID': client_id.strip(), prefix + '_CLIENT_SECRET': client_secret.strip(), 'MAIL_PUBLIC_URL': public}
    # Reuse existing keys: replacing them would invalidate connected accounts.
    service = values.get('MAIL_SERVICE_KEY', '')
    token = values.get('MAIL_TOKEN_KEY', '')
    if service and len(service) < 32:
        raise ValueError('MAIL_SERVICE_KEY existentă este invalidă. Corecteaz-o local; nu a fost înlocuită automat.')
    if token:
        try:
            if len(base64.urlsafe_b64decode(token.encode())) != 32:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ValueError('MAIL_TOKEN_KEY existentă este invalidă. Nu o schimba dacă există conturi conectate.') from None
    if not service:
        result['MAIL_SERVICE_KEY'] = secrets.token_urlsafe(48)
    if not token:
        result['MAIL_TOKEN_KEY'] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    if provider == 'microsoft':
        if not re.fullmatch(r'[a-zA-Z0-9.-]+', tenant):
            raise ValueError('Tenant Microsoft invalid.')
        result['MICROSOFT_TENANT'] = tenant
    return result


def save_env(path, updates):
    text = path.read_text(encoding='utf-8')
    remaining = dict(updates)
    lines = []
    def entry(key, value):
        # Compose's $$ prevents interpolation of dollar signs in client secrets.
        value = value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '$$')
        return f'{key}="{value}"'
    for line in text.splitlines():
        match = ASSIGNMENT.match(line)
        if match and match[1] in updates:
            key = match[1]
            lines.append(entry(key, updates[key]))
            remaining.pop(key, None)
        else:
            lines.append(line)
    lines.extend(entry(key, value) for key, value in remaining.items())
    # A private backup, ignored by git, allows recovery without replacing secrets.
    backup = path.with_name(path.name + '.email-backup-' + secrets.token_hex(6))
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    fd, temporary = tempfile.mkstemp(prefix='.env.email-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=('google', 'microsoft'), required=True)
    args = parser.parse_args()
    path = ROOT / '.env'
    if not path.is_file():
        parser.exit(1, 'Lipsește .env. Configurează întâi instalarea conform LANSARE.md.\n')
    try:
        values = read_env(path.read_text(encoding='utf-8'))
        public = input(f"Adresa aplicației [{values.get('MAIL_PUBLIC_URL') or 'http://127.0.0.1:8080'}]: ").strip() or values.get('MAIL_PUBLIC_URL') or 'http://127.0.0.1:8080'
        public = public.rstrip('/')
        validate_public(public)
        print(f'Înregistrează exact acest Redirect URI la furnizor: {public}/api/emails/accounts/{args.provider}/callback')
        client_id = input('Application / Client ID: ').strip()
        secret = getpass.getpass('Client Secret (nu se afișează): ').strip()
        tenant = 'common'
        if args.provider == 'microsoft':
            tenant = input(f"Tenant [{values.get('MICROSOFT_TENANT') or 'common'}]: ").strip() or values.get('MICROSOFT_TENANT') or 'common'
        update = changes(values, args.provider, client_id, secret, public, tenant)
        backup = save_env(path, update)
        print(f'Configurația a fost salvată local. Copia anterioară: {backup.name}')
        print('Nu trimite .env, copia sau cheile în chat. Nu este necesar profilul IMAP mail pentru conectarea OAuth.')
        print('Rulează: docker compose --profile ui up -d --build backend research-gateway frontend')
        print('Apoi reîncarcă pagina și apasă Conectează. Dacă gateway-ul nu pornește: docker compose logs --tail=40 research-gateway')
    except (ValueError, OSError):
        parser.exit(1, 'Configurarea nu s-a finalizat. Verifică valorile și permisiunile locale; cheile existente nu sunt resetate automat.\n')
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, '\nConfigurare anulată.\n')


if __name__ == '__main__':
    main()

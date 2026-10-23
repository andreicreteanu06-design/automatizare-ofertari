import os

import pytest
from cryptography.fernet import Fernet
from scripts.configure_email import read_env, changes, save_env


def test_setup_preserves_existing_secrets_and_other_provider(tmp_path):
    path = tmp_path / '.env'
    key = Fernet.generate_key().decode()
    original = f'# Client settings\nPOSTGRES_PASSWORD="keep-private"\nMAIL_SERVICE_KEY={"s" * 40}\nMAIL_TOKEN_KEY={key}\nMICROSOFT_CLIENT_SECRET="keep-microsoft"\nGOOGLE_CLIENT_ID=\n'
    path.write_text(original)
    update = changes(read_env(original), 'google', 'client-id', 'secret-$DOLLAR-"quote"', 'http://127.0.0.1:8080')
    backup = save_env(path, update)
    result = read_env(path.read_text())
    assert result['GOOGLE_CLIENT_SECRET'] == 'secret-$DOLLAR-"quote"'
    assert result['POSTGRES_PASSWORD'] == 'keep-private'
    assert result['MICROSOFT_CLIENT_SECRET'] == 'keep-microsoft'
    assert result['MAIL_TOKEN_KEY'] == key
    assert result['MAIL_SERVICE_KEY'] == 's' * 40
    assert backup.read_text() == original
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert os.stat(backup).st_mode & 0o777 == 0o600


def test_first_setup_generates_usable_keys_and_reuses_them():
    update = changes({}, 'google', 'id', 'secret', 'http://localhost:8080')
    assert len(update['MAIL_SERVICE_KEY']) >= 32
    cipher = Fernet(update['MAIL_TOKEN_KEY'].encode())
    assert cipher.decrypt(cipher.encrypt(b'test')) == b'test'
    second = changes(update, 'microsoft', 'ms-id', 'ms-secret', 'http://localhost:8080', 'organizations')
    assert 'MAIL_TOKEN_KEY' not in second and 'MAIL_SERVICE_KEY' not in second
    assert second['MICROSOFT_TENANT'] == 'organizations'


@pytest.mark.parametrize('existing', [{'MAIL_SERVICE_KEY': 'short'}, {'MAIL_TOKEN_KEY': 'broken'}])
def test_setup_refuses_to_replace_invalid_existing_keys(existing):
    with pytest.raises(ValueError):
        changes(existing, 'google', 'id', 'secret', 'http://localhost:8080')


@pytest.mark.parametrize('public', ['http://192.168.1.1', 'https://', 'https://user:password@example.com', 'https://example.com/path'])
def test_setup_rejects_invalid_origins(public):
    with pytest.raises(ValueError):
        changes({}, 'google', 'id', 'secret', public)

import asyncio
import socket

import pytest
from fastapi.testclient import TestClient
from stealth_browser import app as browser
from stealth_browser.network import public_url, resolve_public


def test_proxy_pins_tcp_to_validated_ip_and_blocks_private_dns(monkeypatch):
    from stealth_browser import network
    class Writer:
        def __init__(self):
            self.output = b''
        def write(self, data):
            self.output += data
        async def drain(self):
            pass
        def close(self):
            pass
    async def run():
        calls = []
        async def resolve(host, port):
            assert host == 'supplier.example'
            return ['8.8.8.8']
        async def connect(host, port):
            calls.append((host, port))
            remote = asyncio.StreamReader()
            remote.feed_eof()
            return remote, Writer()
        monkeypatch.setattr(network, 'resolve_public', resolve)
        monkeypatch.setattr(network.asyncio, 'open_connection', connect)
        async def request():
            reader = asyncio.StreamReader()
            reader.feed_data(b'CONNECT supplier.example:443 HTTP/1.1\r\n\r\n')
            reader.feed_eof()
            writer = Writer()
            await network.PublicProxy().handle(reader, writer)
            return writer.output
        assert b'200 Connection' in await request()
        assert calls == [('8.8.8.8', 443)]
        async def blocked(host, port):
            raise ValueError('Destination blocked')
        monkeypatch.setattr(network, 'resolve_public', blocked)
        assert b'403 Forbidden' in await request()
        assert len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('url', [
    'http://localhost/', 'http://127.0.0.1/', 'http://[::1]/', 'http://[::ffff:127.0.0.1]/',
    'http://169.254.169.254/', 'http://10.0.0.1/', 'http://192.168.1.1/',
    'http://224.0.0.1/', 'http://router.local/', 'http://postgres/',
    'file:///etc/passwd', 'https://user:pass@public.example/', 'http://public.example:8000/',
    'https://public.example\\@localhost/', 'https://localhost./',
])
def test_non_public_destinations_rejected_before_browser(url):
    assert not public_url(url)
    assert TestClient(browser.app).post('/fetch', json={'url': url}).status_code in (403, 422)


def test_dns_private_and_mixed_records_rejected(monkeypatch):
    async def run():
        loop = asyncio.get_running_loop()
        async def dns(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        monkeypatch.setattr(loop, 'getaddrinfo', dns)
        with pytest.raises(ValueError):
            await resolve_public('supplier.example', 443)
    asyncio.run(run())


def test_fetch_timeout_and_errors_are_sanitized(monkeypatch):
    async def fail(url):
        raise TimeoutError('SecretClient private URL')
    monkeypatch.setattr(browser, 'fetch_page', fail)
    response = TestClient(browser.app).post('/fetch', json={'url': 'https://supplier.example/product'})
    assert response.status_code == 504 and 'SecretClient' not in response.text


def test_plain_http_fetch_contract(monkeypatch):
    async def page(url):
        return {'html': '<p>PART123</p>', 'text': 'PART123', 'url': url}
    monkeypatch.setattr(browser, 'fetch_page', page)
    response = TestClient(browser.app).post('/fetch', json={'url': 'https://supplier.example/product'})
    assert response.status_code == 200 and response.json()['text'] == 'PART123'

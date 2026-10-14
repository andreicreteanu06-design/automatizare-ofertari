"""Small local forward proxy: resolve and connect to the validated IP, not hostname.

This prevents the browser from re-resolving an approved hostname to a private IP.
It is not a replacement for an infrastructure egress firewall.
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


def public_url(url):
    try:
        p = urlsplit(url)
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
                or p.port not in (None, 80, 443) or '\\' in url
                or any(ord(c) < 33 for c in url)):
            return False
        host = p.hostname.rstrip('.').lower()
        if '.' not in host and ':' not in host:
            return False
        if host == 'localhost' or host.endswith(('.local', '.internal', '.localhost')):
            return False
        try:
            return public_ip(host)
        except ValueError:
            return True
    except ValueError:
        return False


def public_ip(value):
    ip = ipaddress.ip_address(value)
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


async def resolve_public(host, port):
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(r[4][0] for r in records))
    if not addresses or not all(public_ip(ip) for ip in addresses):
        raise ValueError('Destination blocked')
    return addresses


async def relay(reader, writer):
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()


class PublicProxy:
    def __init__(self):
        self.tasks = set()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=32768)
        self.url = f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}'
        return self

    async def __aexit__(self, *args):
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        upstream = None
        try:
            async with asyncio.timeout(55):
                header = await reader.readuntil(b'\r\n\r\n')
                method, target, version = header.split(b'\r\n', 1)[0].decode('ascii').split(' ', 2)
                if method not in ('CONNECT', 'GET', 'HEAD'):
                    raise ValueError('Method blocked')
                url = 'https://' + target if method == 'CONNECT' else target
                if not public_url(url):
                    raise ValueError('Destination blocked')
                parts = urlsplit(url)
                port = parts.port or (443 if parts.scheme == 'https' else 80)
                addresses = await resolve_public(parts.hostname, port)
                # Pin the actual TCP destination. The browser never resolves this host itself.
                remote, upstream = await asyncio.open_connection(addresses[0], port)
                if method == 'CONNECT':
                    writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    await writer.drain()
                else:
                    path = (parts.path or '/') + ('?' + parts.query if parts.query else '')
                    # One origin per connection, no proxy credentials / connection reuse.
                    headers = [line for line in header.split(b'\r\n')[1:-2]
                               if line.split(b':', 1)[0].lower() not in (b'proxy-authorization', b'proxy-connection', b'connection', b'host')]
                    request = f'{method} {path} {version}\r\nHost: {parts.netloc}\r\nConnection: close\r\n'.encode() + b'\r\n'.join(headers) + b'\r\n\r\n'
                    upstream.write(request)
                    await upstream.drain()
                tasks = [asyncio.create_task(relay(reader, upstream)), asyncio.create_task(relay(remote, writer))]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (ValueError, OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            try:
                writer.write(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n')
                await writer.drain()
            except OSError:
                pass
        finally:
            if upstream:
                upstream.close()
            writer.close()
            self.tasks.discard(task)

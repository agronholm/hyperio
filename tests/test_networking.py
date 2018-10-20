import ssl
import sys
from pathlib import Path

import pytest

from anyio import (
    create_task_group, connect_tcp, create_udp_socket, connect_unix, create_unix_server,
    create_tcp_server)
from anyio.exceptions import IncompleteRead, DelimiterNotFound, ClosedResourceError


@pytest.mark.anyio
async def test_connect_tcp():
    async def server():
        async with await stream_server.accept() as stream:
            command = await stream.receive_some(100)
            await stream.send_all(command[::-1])

    async with create_task_group() as tg:
        async with await create_tcp_server(interface='localhost') as stream_server:
            await tg.spawn(server)
            async with await connect_tcp('localhost', stream_server.port) as client:
                await client.send_all(b'blah')
                response = await client.receive_some(100)

    assert response == b'halb'


@pytest.mark.anyio
async def test_connect_tcp_tls():
    async def server():
        async with await stream_server.accept() as stream:
            command = await stream.receive_some(100)
            await stream.send_all(command[::-1])

    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(certfile=str(Path(__file__).with_name('cert.pem')),
                                   keyfile=str(Path(__file__).with_name('key.pem')))
    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    client_context.load_verify_locations(cafile=str(Path(__file__).with_name('cert.pem')))
    async with create_task_group() as tg:
        async with await create_tcp_server(
                interface='localhost', ssl_context=server_context) as stream_server:
            await tg.spawn(server)
            async with await connect_tcp('localhost', stream_server.port,
                                         tls=client_context) as client:
                await client.send_all(b'blah')
                response = await client.receive_some(100)

    assert response == b'halb'


@pytest.mark.skipif(sys.platform == 'win32', reason='UNIX sockets are not available on Windows')
@pytest.mark.parametrize('as_path', [False])
@pytest.mark.anyio
async def test_connect_unix(tmpdir, as_path):
    async def server():
        async with await stream_server.accept() as stream:
            command = await stream.receive_some(100)
            await stream.send_all(command[::-1])

    async with create_task_group() as tg:
        path = str(tmpdir.join('socket'))
        if as_path:
            path = Path(path)

        async with await create_unix_server(path) as stream_server:
            await tg.spawn(server)
            async with await connect_unix(path) as client:
                await client.send_all(b'blah')
                response = await client.receive_some(100)

    assert response == b'halb'


@pytest.mark.parametrize('method_name, params', [
    ('receive_until', [b'\n', 100]),
    ('receive_exactly', [5])
], ids=['read_until', 'read_exactly'])
@pytest.mark.anyio
async def test_read_partial(method_name, params):
    async def server():
        async with await stream_server.accept() as stream:
            method = getattr(stream, method_name)
            line1 = await method(*params)
            line2 = await method(*params)
            await stream.send_all(line1.strip() + line2.strip())

    async with create_task_group() as tg:
        async with await create_tcp_server(interface='localhost') as stream_server:
            await tg.spawn(server)
            async with await connect_tcp('localhost', stream_server.port) as client:
                await client.send_all(b'bla')
                await client.send_all(b'h\nb')
                await client.send_all(b'leh\n')
                response = await client.receive_some(100)

    assert response == b'blahbleh'


@pytest.mark.parametrize('method_name, params', [
    ('receive_until', [b'\n', 100]),
    ('receive_exactly', [5])
], ids=['read_until', 'read_exactly'])
@pytest.mark.anyio
async def test_incomplete_read(method_name, params):
    async def server():
        async with await stream_server.accept() as stream:
            await stream.send_all(b'bla')

    async with create_task_group() as tg:
        async with await create_tcp_server(interface='localhost') as stream_server:
            await tg.spawn(server)
            async with await connect_tcp('localhost', stream_server.port) as client:
                method = getattr(client, method_name)
                with pytest.raises(IncompleteRead) as exc:
                    await method(*params)

                assert exc.value.data == b'bla'


@pytest.mark.anyio
async def test_delimiter_not_found():
    async def server():
        async with await stream_server.accept() as stream:
            await stream.send_all(b'blah\n')

    async with create_task_group() as tg:
        async with await create_tcp_server(interface='localhost') as stream_server:
            await tg.spawn(server)
            async with await connect_tcp('localhost', stream_server.port) as client:
                with pytest.raises(DelimiterNotFound) as exc:
                    await client.receive_until(b'\n', 3)

                assert exc.value.data == b'bla'


@pytest.mark.anyio
async def test_receive_chunks():
    async def server():
        async with await stream_server.accept() as stream:
            async for chunk in stream.receive_chunks(2):
                chunks.append(chunk)

    chunks = []
    async with await create_tcp_server(interface='localhost') as stream_server:
        async with create_task_group() as tg:
            await tg.spawn(server)
            async with await connect_tcp('localhost', stream_server.port) as client:
                await client.send_all(b'blah')

    assert chunks == [b'bl', b'ah']


@pytest.mark.anyio
async def test_receive_delimited_chunks():
    async def server():
        async with await stream_server.accept() as stream:
            async for chunk in stream.receive_delimited_chunks(b'\r\n', 8):
                chunks.append(chunk)

    chunks = []
    async with await create_tcp_server(interface='localhost') as stream_server:
        async with create_task_group() as tg:
            await tg.spawn(server)
            async with await connect_tcp('localhost', stream_server.port) as client:
                for chunk in (b'bl', b'ah', b'\r', b'\nfoo', b'bar\r\n'):
                    await client.send_all(chunk)

    assert chunks == [b'blah', b'foobar']


@pytest.mark.anyio
async def test_udp():
    async with await create_udp_socket(port=5000, interface='localhost',
                                       target_port=5000, target_host='localhost') as socket:
        await socket.send(b'blah')
        request, addr = await socket.receive(100)
        assert request == b'blah'
        assert addr == ('127.0.0.1', 5000)

        await socket.send(b'halb')
        response, addr = await socket.receive(100)
        assert response == b'halb'
        assert addr == ('127.0.0.1', 5000)


@pytest.mark.anyio
async def test_udp_noconnect():
    async with await create_udp_socket(interface='localhost') as socket:
        await socket.send(b'blah', 'localhost', socket.port)
        request, addr = await socket.receive(100)
        assert request == b'blah'
        assert addr == ('127.0.0.1', socket.port)

        await socket.send(b'halb', 'localhost', socket.port)
        response, addr = await socket.receive(100)
        assert response == b'halb'
        assert addr == ('127.0.0.1', socket.port)


@pytest.mark.anyio
async def test_udp_close_socket_from_other_task():
    async with create_task_group() as tg:
        async with await create_udp_socket(interface='127.0.0.1') as udp:
            await tg.spawn(udp.close)
            with pytest.raises(ClosedResourceError):
                await udp.receive(100)


@pytest.mark.anyio
async def test_udp_receive_packets():
    async def serve():
        async for packet, addr in server.receive_packets(10000):
            await server.send(packet[::-1], *addr)

    async with await create_udp_socket(interface='127.0.0.1') as server:
        async with await create_udp_socket(target_host='127.0.0.1',
                                           target_port=server.port) as client:
            async with create_task_group() as tg:
                await tg.spawn(serve)
                await client.send(b'FOOBAR')
                assert await client.receive(100) == (b'RABOOF', ('127.0.0.1', server.port))
                await client.send(b'123456')
                assert await client.receive(100) == (b'654321', ('127.0.0.1', server.port))
                await tg.cancel_scope.cancel()

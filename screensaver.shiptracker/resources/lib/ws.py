"""A tiny RFC 6455 WebSocket client over a plain socket.

Kodi's Python does not ship the third-party ``websockets`` package, and the AIS stream only
needs the client half of the protocol: an HTTP upgrade, masked text frames out and unmasked
text or binary frames in, plus ping/pong and close. The frame helpers are plain functions so
they can be tested without a socket.
"""

import base64
import hashlib
import os
import socket
import ssl
import struct
import time

from . import net

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 8, 9, 10


class WebSocketError(Exception):
    pass


class WebSocketClosed(WebSocketError):
    pass


def mask(payload, key):
    return bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))


def build_frame(opcode, payload, key=None, fin=True):
    """One client frame. A key masks the payload; server frames are sent without one."""
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    first = (0x80 if fin else 0) | (opcode & 0x0F)
    length = len(payload)
    header = bytearray([first])
    flag = 0x80 if key else 0
    if length < 126:
        header.append(flag | length)
    elif length < 65536:
        header.append(flag | 126)
        header += struct.pack('!H', length)
    else:
        header.append(flag | 127)
        header += struct.pack('!Q', length)
    if key:
        header += key
        payload = mask(payload, key)
    return bytes(header) + payload


def parse_frame(buffer):
    """(fin, opcode, payload, consumed) for the first complete frame, or None.

    Server frames are normally unmasked; a masked one is accepted too and unmasked. The caller
    keeps the unconsumed bytes, so a partial frame simply returns None until more arrive.
    """
    if len(buffer) < 2:
        return None
    first, second = buffer[0], buffer[1]
    fin = bool(first & 0x80)
    if first & 0x70:
        raise WebSocketError('unsupported reserved bits (compression?)')
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    offset = 2
    if length == 126:
        if len(buffer) < 4:
            return None
        length = struct.unpack('!H', buffer[2:4])[0]
        offset = 4
    elif length == 127:
        if len(buffer) < 10:
            return None
        length = struct.unpack('!Q', buffer[2:10])[0]
        offset = 10
    key = None
    if masked:
        if len(buffer) < offset + 4:
            return None
        key = buffer[offset:offset + 4]
        offset += 4
    if len(buffer) < offset + length:
        return None
    payload = bytes(buffer[offset:offset + length])
    if key:
        payload = mask(payload, key)
    return fin, opcode, payload, offset + length


def accept_key(key):
    digest = hashlib.sha1((key + GUID).encode('ascii')).digest()
    return base64.b64encode(digest).decode('ascii')


class WebSocket(object):
    def __init__(self, host, port=443, path='/', timeout=15, secure=True, sock=None):
        self.host = host
        self.port = port
        self.path = path
        self.timeout = timeout
        self.secure = secure
        self._sock = sock
        self._buffer = b''
        self._message = bytearray()
        self._message_opcode = None

    def connect(self):
        if self._sock is not None:
            return self
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.secure:
            raw = net._CONTEXT.wrap_socket(raw, server_hostname=self.host)
        self._sock = raw
        self._sock.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        request = (
            'GET %s HTTP/1.1\r\n'
            'Host: %s\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            'Sec-WebSocket-Key: %s\r\n'
            'Sec-WebSocket-Version: 13\r\n'
            'User-Agent: %s\r\n'
            '\r\n' % (self.path, self.host, key, net.USER_AGENT)
        )
        self._sock.sendall(request.encode('ascii'))
        head = b''
        while b'\r\n\r\n' not in head:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError('connection closed during the upgrade')
            head += chunk
            if len(head) > 65536:
                raise WebSocketError('upgrade response too large')
        header, self._buffer = head.split(b'\r\n\r\n', 1)
        lines = header.decode('latin-1').split('\r\n')
        status = lines[0].split(' ', 2)
        if len(status) < 2 or status[1] != '101':
            raise WebSocketError('upgrade refused: %s' % lines[0])
        fields = {}
        for line in lines[1:]:
            name, _, value = line.partition(':')
            fields[name.strip().lower()] = value.strip()
        expected = accept_key(key)
        if fields.get('sec-websocket-accept') != expected:
            raise WebSocketError('bad Sec-WebSocket-Accept')
        return self

    def _send(self, opcode, payload, fin=True):
        if self._sock is None:
            raise WebSocketError('not connected')
        key = os.urandom(4)
        self._sock.sendall(build_frame(opcode, payload, key=key, fin=fin))

    def send_text(self, text):
        self._send(OP_TEXT, text)

    def _finish_message(self):
        payload = bytes(self._message)
        self._message = bytearray()
        self._message_opcode = None
        try:
            return payload.decode('utf-8')
        except UnicodeDecodeError as error:
            raise WebSocketError('message is not UTF-8: %s' % error)

    def recv_text(self, timeout=None):
        """The next complete text/binary message, or None when timeout expires."""
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            frame = parse_frame(self._buffer)
            if frame is not None:
                fin, opcode, payload, consumed = frame
                self._buffer = self._buffer[consumed:]
                if opcode == OP_CLOSE:
                    raise WebSocketClosed('closed by server')
                if opcode == OP_PING:
                    try:
                        self._send(OP_PONG, payload)
                    except OSError:
                        raise WebSocketClosed('closed while answering a ping')
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode in (OP_TEXT, OP_BINARY):
                    if fin:
                        return self._finish_message_with(payload)
                    self._message = bytearray(payload)
                    self._message_opcode = opcode
                    continue
                if opcode == OP_CONT:
                    if self._message_opcode is None:
                        raise WebSocketError('continuation without a start frame')
                    self._message += payload
                    if fin:
                        return self._finish_message()
                    continue
                raise WebSocketError('unexpected opcode %d' % opcode)

            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
            else:
                left = None
            if self._sock is None:
                raise WebSocketClosed('not connected')
            try:
                self._sock.settimeout(left)
                chunk = self._sock.recv(65536)
            except socket.timeout:
                return None
            except OSError as error:
                raise WebSocketClosed('connection lost: %s' % error)
            if not chunk:
                raise WebSocketClosed('connection closed')
            self._buffer += chunk

    def _finish_message_with(self, payload):
        self._message = bytearray()
        self._message_opcode = None
        try:
            return payload.decode('utf-8')
        except UnicodeDecodeError as error:
            raise WebSocketError('message is not UTF-8: %s' % error)

    def close(self):
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            key = os.urandom(4)
            sock.sendall(build_frame(OP_CLOSE, b'', key=key))
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

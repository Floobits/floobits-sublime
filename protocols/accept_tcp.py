import socket


try:
    from . import base
except (ImportError, ValueError):
    import base


class ListenerProtocol(base.BaseProtocol):
    def __init__(self, host, port):
        super(ListenerProtocol, self).__init__(host, port, False)
        self.host = host
        self.port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(1)

    def __len__(self):
        return 0

    def fileno(self):
        return self._sock

    def fd_set(self, readable, writeable, errorable):
        readable.append(self._sock)

    def read(self):
        conn, addr = self._sock.accept()
        conn.setblocking(False)
        self.emit("connect", conn, addr)

try:
    from .. import event_emitter
except (ImportError, ValueError):
    from floo.common import event_emitter


class BaseProtocol(event_emitter.EventEmitter):
    ''' Base FD Interface'''

    def __init__(self, host, port, secure=True):
        super(BaseProtocol, self).__init__()

        self.host = host
        self.port = port
        self.secure = secure

    def __len__(self):
        return 0

    def listen(self):
        raise NotImplemented()

    def fileno(self):
        raise NotImplemented()

    def fd_set(self, readable, writeable, errorable):
        raise NotImplemented()

    def cleanup(self):
        raise NotImplemented()

    def write(self):
        raise NotImplemented()

    def read(self):
        raise NotImplemented()

    def error(self):
        raise NotImplemented()

    def reconnect(self):
        raise NotImplemented()

    def stop(self):
        self.cleanup()

    def connect(self, conn=None):
        self.emit("connect", conn)

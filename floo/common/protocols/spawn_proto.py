import subprocess
import collections
import os

try:
    import ssl
    assert ssl
except ImportError:
    ssl = False
try:
    from .. import msg, shared as G, utils
    from . import base
    assert G and msg and utils
except (ImportError, ValueError):
    from floo.common import msg, shared as G, utils
    import base


class SpawnProto(base.BaseProtocol):
    def __init__(self, args):
        self._q = collections.deque()
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def __len__(self):
        return len(self._q)

    @property
    def stdin(self):
        return self.proc.stdin.fileno()

    @property
    def stdout(self):
        return self.proc.stdout.fileno()

    @property
    def stderr(self):
        return self.proc.stderr.fileno()
    
    def fileno(self):
        print(self.proc.poll())
        return (self.stdout, self.stderr)

    def fd_set(self, readable, writeable, errorable):
        stdout = self.stdout
        stderr = self.stderr
        readable.add(stdout)
        readable.add(stderr)
        errorable.add(stderr)

        if len(self) > 0:
            stdin = self.stdin
            writeable.add(stdin)
            errorable.add(stdin)

    def cleanup(self):
        self._q = collections.deque()
        self.proc.kill()

    def write(self):
        while self._q:
            item = self._q.popleft()
            os.write(self.stdin, item)

    def read(self):
        print(os.read(self.stdout))

    def error(self):
        raise NotImplementedError("error not implemented.")

    def reconnect(self):
        import sys
        sys.exit(1)

    def stop(self):
        self.cleanup()

    def connect(self, conn=None):
        self.emit("connect", conn)

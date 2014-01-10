import subprocess
import collections
import os
import re

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
    def __init__(self, handler, args):
        super(SpawnProto, self).__init__(None, None, None)
        self.handler = handler
        self._q = collections.deque()
        print("working dir: %s. args: %s" % (G.PLUGIN_PATH, args))
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=G.PLUGIN_PATH)
        # line = os.read(self.proc.stdout.fileno(), 4096)
        # line = ''
        # while True:
        #     try:
        #         d = os.read(self.proc.stdout.fileno(), 4096)
        #         if not d or d == '':
        #             break
        #         line += d
        #         if line[-1] == '\n':
        #             break
        #     except (IOError, OSError):
        #         break
        line = self.proc.stdout.readline()
        print("read line: %s" % line)
        match = re.search('Now listening on <(\d+)>', line)
        if not match:
            # for line in self.proc.stdout:
            #     print(line)
            raise Exception("no port?!" + line)
        self.handler.emit('port', 9999)  # int(match.group(1)))

    def __len__(self):
        return len(self._q)

    @property
    def stdin(self):
        return self.proc.stdin.fileno()

    @property
    def stdout(self):
        return self.proc.stdout.fileno()

    def fileno(self):
        return self.stdout

    def fd_set(self, readable, writeable, errorable):
        readable.append(self.stdout)
        errorable.append(self.stdout)

        # if len(self) > 0:
        #     stdin = self.stdin
        #     writeable.append(stdin)
        #     errorable.append(stdin)

    def cleanup(self):
        self._q = collections.deque()
        self.proc.kill()

    def write(self):
        return
        while self._q:
            item = self._q.popleft()
            os.write(self.stdin, item)

    def read(self):
        print('reading')
        buf = b''
        while True:
            try:
                d = os.read(self.stdout, 4096)
                if not d or d == '':
                    break
                buf += d
            except (IOError, OSError):
                break
        if buf:
            msg.log("from proxy", buf)

    def error(self):
        raise NotImplementedError("error not implemented.")

    def reconnect(self):
        import sys
        sys.exit(1)

    def stop(self):
        self.cleanup()

    def connect(self, conn=None):
        self.emit("connect", conn)

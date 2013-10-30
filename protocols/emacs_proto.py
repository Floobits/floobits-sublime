import sys
import json
import errno


try:
    import ssl
    assert ssl
except ImportError:
    ssl = False
try:
    from .. import editor, msg, shared as G, utils
    from . import floo_proto
    assert G and msg and utils
except (ImportError, ValueError):
    from floo import editor, msg, shared as G, utils
    import floo_proto

try:
    connect_errno = (errno.WSAEWOULDBLOCK, errno.WSAEALREADY, errno.WSAEINVAL)
    iscon_errno = errno.WSAEISCONN
except Exception:
    connect_errno = (errno.EINPROGRESS, errno.EALREADY)
    iscon_errno = errno.EISCONN


CHAT_VIEW = None
PY2 = sys.version_info < (3, 0)


def sock_debug(*args, **kwargs):
    if G.SOCK_DEBUG:
        msg.log(*args, **kwargs)


class EmacsProtocol(floo_proto.FlooProtocol):
    ''' Base FD Interface'''
    NEWLINE = '\n'.encode('utf-8')
    MAX_RETRIES = -1
    INITIAL_RECONNECT_DELAY = 500

    def _handle(self, data):
        self._buf += data
        while True:
            before, sep, after = self._buf.partition(self.NEWLINE)
            if not sep:
                return
            try:
                # Node.js sends invalid utf8 even though we're calling write(string, "utf8")
                # Python 2 can figure it out, but python 3 hates it and will die here with some byte sequences
                # Instead of crashing the plugin, we drop the data. Yes, this is horrible.
                before = before.decode('utf-8', 'ignore')
                data = json.loads(before)
            except Exception as e:
                msg.error('Unable to parse json: %s' % str(e))
                msg.error('Data: %s' % before)
                # XXXX: THIS LOSES DATA
                self._buf = after
                continue
            name = data.get('name')
            try:
                self.emit("data", name, data)
                msg.debug("got data " + name)
            except Exception as e:
                print(e)
                msg.error('Error handling %s event (%s).' % (name, str(e)))
                if name == 'room_info':
                    editor.error_message('Error joining workspace: %s' % str(e))
                    self.stop()
            self._buf = after

    def fd_set(self, readable, writeable, errorable):
        if not self._sock:
            return

        fileno = self.fileno()
        errorable.append(fileno)
        readable.append(self._sock)
        if len(self) > 0:
            writeable.append(fileno)

    def connect(self, conn):
        self.connected = True
        self._sock = conn

    def cleanup(self, *args, **kwargs):
        try:
            self._sock.shutdown(2)
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass
        G.JOINED_WORKSPACE = False
        self._buf = bytes()
        self._sock = None
        self.connected = False

    def stop(self):
        self.retries = -1
        utils.cancel_timeout(self._reconnect_timeout)
        self._reconnect_timeout = None
        self.cleanup()
        msg.log('Disconnected.')

    def reconnect(self):
        msg.error("emacs connection died")
        sys.exit(1)

    def put(self, item):
        if not item:
            return
        msg.debug('writing %s: %s' % (item.get('name', 'NO NAME'), item))
        self._q.append(json.dumps(item) + '\n')
        qsize = len(self._q)
        msg.debug('%s items in q' % qsize)
        return qsize

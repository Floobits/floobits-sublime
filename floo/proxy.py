# coding: utf-8

from __future__ import print_function

from collections import defaultdict
import json
import optparse
import platform
import sys
import time
import copy

# Monkey patch editor
timeouts = defaultdict(list)
top_timeout_id = 0
cancelled_timeouts = set()
calling_timeouts = False


def name():
    if sys.version_info < (3, 0):
        py_version = 2
    else:
        py_version = 3
    return 'Floozy-%s' % py_version


def ok_cancel_dialog(dialog):
    print('Dialog:', dialog)


def error_message(msg):
    print(msg, file=sys.stderr)


def status_message(msg):
    print(msg)


def _platform():
    return platform.platform()


def set_timeout(func, timeout, *args, **kwargs):
    global top_timeout_id
    timeout_id = top_timeout_id
    top_timeout_id + 1
    if top_timeout_id > 100000:
        top_timeout_id = 0

    def timeout_func():
        if timeout_id in cancelled_timeouts:
            cancelled_timeouts.remove(timeout_id)
            return
        func(*args, **kwargs)

    then = time.time() + (timeout / 1000.0)
    timeouts[then].append(timeout_func)
    return timeout_id


def cancel_timeout(timeout_id):
    if timeout_id in timeouts:
        cancelled_timeouts.add(timeout_id)


def call_timeouts():
    global calling_timeouts
    if calling_timeouts:
        return
    calling_timeouts = True
    now = time.time()
    for t, tos in copy.copy(timeouts).items():
        if now >= t:
            for timeout in tos:
                timeout()
            del timeouts[t]
    calling_timeouts = False


def open_file(file):
    pass


try:
    from .common import api, msg, shared as G, utils, reactor, event_emitter
    from .common.handlers import base
    from .common.protocols import floo_proto
    from . import editor
except (ImportError, ValueError):
    from common import api, msg, shared as G, utils, reactor, event_emitter
    from common.handlers import base
    from common.protocols import floo_proto
    import editor


def editor_log(msg):
    print(msg)
    sys.stdout.flush()


editor.name = name
editor.ok_cancel_dialog = ok_cancel_dialog
editor.error_message = error_message
editor.status_message = status_message
editor.platform = _platform
editor.set_timeout = set_timeout
editor.cancel_timeout = cancel_timeout
editor.call_timeouts = call_timeouts
editor.open_file = open_file
msg.editor_log = editor_log

utils.reload_settings()
eventStream = event_emitter.EventEmitter()


def conn_log(action, item):
    try:
        item = item.decode('utf-8')
    except Exception:
        pass
    if G.SOCK_DEBUG:
        msg.log(action, ': ', item)
    sys.stdout.flush()


eventStream.on('to_floobits', lambda x: conn_log('to_floobits', x))
eventStream.on('from_floobits', lambda x: conn_log('from_floobits', x))


# KANS: this should use base, but I want the connection logic from FlooProto (ie, move that shit to base)
class RemoteProtocol(floo_proto.FlooProtocol):
    ''' Speaks floo proto, but is given the conn and we don't want to reconnect '''
    MAX_RETRIES = -1

    def __init__(self, *args, **kwargs):
        super(RemoteProtocol, self).__init__(*args, **kwargs)
        eventStream.on('to_floobits', self._q.append)

    def _handle(self, data):
        # Node.js sends invalid utf8 even though we're calling write(string, "utf8")
        # Python 2 can figure it out, but python 3 hates it and will die here with some byte sequences
        # Instead of crashing the plugin, we drop the data. Yes, this is horrible.
        data = data.decode('utf-8', 'ignore')
        eventStream.emit('from_floobits', data)

    def reconnect(self):
        msg.error('Remote connection died')
        sys.exit(1)


class FlooConn(base.BaseHandler):
    PROTOCOL = RemoteProtocol

    def __init__(self, server):
        super(FlooConn, self).__init__()

    def tick(self):
        pass

    def on_connect(self):
        msg.log('Remote connection estabished.')
        eventStream.emit('remote_conn')


class LocalProtocol(floo_proto.FlooProtocol):
    ''' Speaks floo proto, but is given the conn and we don't want to reconnect '''
    MAX_RETRIES = -1
    INITIAL_RECONNECT_DELAY = 0

    def __init__(self, *args, **kwargs):
        super(LocalProtocol, self).__init__(*args, **kwargs)
        eventStream.on('from_floobits', self._q.append)
        self.to_proxy = []
        self.remote_conn = False
        eventStream.on('remote_conn', self.on_remote_conn)

    def connect(self, sock=None):
        self.emit('connect')
        self._sock = sock
        self.connected = True

    def reconnect(self):
        msg.error('Client connection died')
        sys.exit(1)

    def stop(self):
        self.cleanup()

    def on_remote_conn(self):
        self.remote_conn = True
        while self.to_proxy:
            item = self.to_proxy.pop(0)
            eventStream.emit('to_floobits', item.decode('utf-8'))

    def _handle(self, data):
        if self.remote_conn:
            eventStream.emit('to_floobits', data.decode('utf-8'))
        else:
            self.to_proxy.append(data)


remote_host = G.DEFAULT_HOST
remote_port = G.DEFAULT_PORT
remote_ssl = True


class Server(base.BaseHandler):
    PROTOCOL = LocalProtocol

    def on_connect(self):
        self.conn = FlooConn(self)
        reactor.reactor.connect(self.conn, remote_host, remote_port, remote_ssl)


try:
    import urllib
    HTTPError = urllib.error.HTTPError
    URLError = urllib.error.URLError
except (AttributeError, ImportError, ValueError):
    import urllib2
    HTTPError = urllib2.HTTPError
    URLError = urllib2.URLError


def main():
    global remote_host, remote_port, remote_ssl
    msg.LOG_LEVEL = msg.LOG_LEVELS['ERROR']

    usage = 'Figure it out :P'
    parser = optparse.OptionParser(usage=usage)
    parser.add_option(
        '--url',
        dest='url',
        default=None
    )
    parser.add_option(
        '--data',
        dest='data',
        default=None
    )
    parser.add_option(
        '--method',
        dest='method',
        default=None
    )
    parser.add_option(
        '--host',
        dest='host',
        default=None
    )
    parser.add_option(
        '--port',
        dest='port',
        default=None
    )
    parser.add_option(
        '--ssl',
        dest='ssl',
        default=None
    )

    options, args = parser.parse_args()

    if options.url:
        data = None
        err = False
        if options.data:
            data = json.loads(options.data)
        try:
            r = api.hit_url(options.host, options.url, data, options.method)
        except HTTPError as e:
            r = e
        except URLError as e:
            r = e
            err = True

        try:
            print(r.code)
        except Exception:
            err = True
        if err:
            print(r.reason)
        else:
            print(r.read().decode('utf-8'))
        sys.exit(err)

    if not options.host:
        sys.exit(1)

    remote_host = options.host
    remote_port = int(options.port) or remote_port
    remote_ssl = bool(options.ssl) or remote_ssl

    proxy = Server()
    _, port = reactor.reactor.listen(proxy, port=int(G.PROXY_PORT))

    def on_ready():
        print('Now listening on <%s>' % port)
        sys.stdout.flush()

    utils.set_timeout(on_ready, 100)

    try:
        reactor.reactor.block()
    except KeyboardInterrupt:
        print('ciao')


if __name__ == '__main__':
    main()

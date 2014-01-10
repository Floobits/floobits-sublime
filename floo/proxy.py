# coding: utf-8

from __future__ import print_function

import sys
import platform
from collections import defaultdict
import time

import editor

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
    print("Dialog: ", dialog)


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
    to_remove = []
    for t, tos in timeouts.items():
        if now >= t:
            for timeout in tos:
                timeout()
            to_remove.append(t)
    for k in to_remove:
        del timeouts[k]
    calling_timeouts = False


def open_file(file):
    pass

editor.name = name
editor.ok_cancel_dialog = ok_cancel_dialog
editor.error_message = error_message
editor.status_message = status_message
editor.platform = _platform
editor.set_timeout = set_timeout
editor.cancel_timeout = cancel_timeout
editor.call_timeouts = call_timeouts
editor.open_file = open_file

try:
    from common import msg, shared as G, utils, reactor, event_emitter
    from common.handlers import base
    from common.protocols import floo_proto
except (ImportError, ValueError):
    from .common import msg, shared as G, reactor, event_emitter
    from .common.handlers import base
    from .common.protocols import floo_proto

eventStream = event_emitter.EventEmitter()
eventStream.on('to_floobits', lambda x: msg.log("to_floobits: " + x) and sys.stdout.flush())
eventStream.on('from_floobits', lambda x: msg.log("from_floobits: " + x))


# KANS: this should use base, but I want the connection logic from FlooProto (ie, move that shit to base)
class RemoteProtocol(floo_proto.FlooProtocol):
    ''' Speaks floo proto, but is given the conn and we don't want to reconnect '''
    MAX_RETRIES = -1

    def __init__(self, *args, **kwargs):
        super(RemoteProtocol, self).__init__(*args, **kwargs)
        eventStream.on('to_floobits', self._q.append)

    def _handle(self, data):
        eventStream.emit('from_floobits', data)

    def reconnect(self):
        msg.error("Remote connection died")
        sys.exit(1)


class FlooConn(base.BaseHandler):
    PROTOCOL = RemoteProtocol

    def __init__(self, server):
        super(FlooConn, self).__init__()

    def tick(self):
        pass

    def on_connect(self):
        msg.log("have a remote conn!")
        eventStream.emit("remote_conn")


class LocalProtocol(floo_proto.FlooProtocol):
    ''' Speaks floo proto, but is given the conn and we don't want to reconnect '''
    MAX_RETRIES = -1
    INITIAL_RECONNECT_DELAY = 0

    def __init__(self, *args, **kwargs):
        super(LocalProtocol, self).__init__(*args, **kwargs)
        eventStream.on('from_floobits', self._q.append)
        self.to_proxy = []
        self.remote_conn = False
        eventStream.on("remote_conn", self.on_remote_conn)

    def connect(self, sock=None):
        self.emit('connect')
        self._sock = sock
        self.connected = True

    def reconnect(self):
        msg.error("Client connection died")
        sys.exit(1)

    def stop(self):
        self.cleanup()

    def on_remote_conn(self):
        self.remote_conn = True
        while self.to_proxy:
            item = self.to_proxy.pop(0)
            eventStream.emit('to_floobits', item)

    def _handle(self, data):
        if self.remote_conn:
            eventStream.emit('to_floobits', data)
        else:
            self.to_proxy.append(data)


class Server(base.BaseHandler):
    PROTOCOL = LocalProtocol

    def on_connect(self):
        self.conn = FlooConn(self)
        reactor.reactor.connect(self.conn, G.DEFAULT_HOST, G.DEFAULT_PORT, True)


def main():
    msg.LOG_LEVEL = msg.LOG_LEVELS.get(msg.LOG_LEVELS['ERROR'])
    proxy = Server()
    _, port = reactor.reactor.listen(proxy)

    def on_ready():
        print('Now listening on <%s>' % port)
        sys.stdout.flush()

    utils.set_timeout(on_ready, 100)

    try:
        reactor.reactor.block()
    except KeyboardInterrupt:
        print("ciao")

if __name__ == "__main__":
    main()

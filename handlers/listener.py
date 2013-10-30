try:
    from . import base
    from .. protocols import accept_tcp
except (ImportError, ValueError):
    from floo.common.protocols import accept_tcp
    import base


class ListenerHandler(base.BaseHandler):
    PROTOCOL = accept_tcp.ListenerProtocol

    def __init__(self, factory, reactor):
        self.factory = factory
        self.reactor = reactor

    def build_protocol(self, *args):
        return self.PROTOCOL(*args)

    def is_ready(self):
        return True

    def on_connect(self, conn, addr):
        #TODO: pass addr along maybe?
        self.reactor.connect(self.factory, None, None, None, conn=conn)

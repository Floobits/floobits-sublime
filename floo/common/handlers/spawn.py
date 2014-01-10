try:
    from . import base
    from .. import event_emitter
    from ..protocols import spawn_proto
except (ImportError, ValueError) as e:
    import base
    from floo.common import event_emitter
    from floo.common.protocols import spawn_proto


class Spawn(base.BaseHandler):
    PROTOCOL = spawn_proto.SpawnProto

    def __init__(self):
        event_emitter.EventEmitter.__init__(self)

    def build_protocol(self, *args):
        self.proto = self.PROTOCOL(self, *args)
        self.proto.on("data", self.on_data)
        self.proto.on("connect", self.on_connect)
        return self.proto

    def on_connect(self):
        pass

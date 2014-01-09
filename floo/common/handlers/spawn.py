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
        super(event_emitter.EventEmitter, self).__init__()

    # def build_protocol(self, *args):
    #     proto = super(Spawn, self).build_protocol(*args)
    #     return proto
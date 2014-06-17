try:
    from .. import api, shared as G
    from ... import editor
    from ..exc_fmt import str_e
    from ..protocols import floo_proto
except (ImportError, ValueError):
    from floo import editor
    from floo.common import api, shared as G
    from floo.common.exc_fmt import str_e
    from floo.common.protocols import floo_proto


PORT_BLOCK_MSG = '''The Floobits plugin can't work because outbound traffic on TCP port 3448 is being blocked.

See https://%s/help/network'''


class NoReconnectProto(floo_proto.FlooProtocol):
    def reconnect(self):
        try:
            api.get_workspace(self.host, 'Floobits', 'doesnotexist')
        except Exception as e:
            print(str_e(e))
            editor.error_message('Something went wrong. See https://%s/help/floorc to complete the installation.' % self.host)
        else:
            if not G.OUTBOUND_FILTERING:
                G.OUTBOUND_FILTERING = True
                return super(NoReconnectProto, self).reconnect()
            editor.error_message('Something went wrong. See https://%s/help/floorc to complete the installation.' % self.host)
        self.stop()

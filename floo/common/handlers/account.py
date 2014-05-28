import os
import sys
import traceback
import getpass

try:
    from . import base
    from .. import msg, api, shared as G, utils
    from ....floo import editor
    from ..exc_fmt import str_e
    from ..protocols import no_reconnect
    assert api and G and msg and utils
except (ImportError, ValueError):
    import base
    from floo import editor
    from floo.common.protocols import no_reconnect
    from floo.common.exc_fmt import str_e
    from .. import msg, api, shared as G, utils


class CreateAccountHandler(base.BaseHandler):
    PROTOCOL = no_reconnect.NoReconnectProto
    # TODO: timeout after 60 seconds

    def on_connect(self):
        try:
            username = getpass.getuser()
        except Exception:
            username = ''

        self.send({
            'name': 'create_user',
            'username': username,
            'client': self.client,
            'platform': sys.platform,
            'version': G.__VERSION__
        })

    def on_data(self, name, data):
        if name == 'create_user':
            del data['name']
            try:
                floorc = self.BASE_FLOORC + '\n'.join(['%s %s' % (k, v) for k, v in data.items()]) + '\n'
                with open(G.FLOORC_PATH, 'w') as floorc_fd:
                    floorc_fd.write(floorc)
                utils.reload_settings()
                if utils.can_auth():
                    p = os.path.join(G.BASE_DIR, 'welcome.md')
                    with open(p, 'w') as fd:
                        text = editor.welcome_text % (G.AUTH.get(self.proto.host, {}).get('username'), self.proto.host)
                        fd.write(text)
                    d = utils.get_persistent_data()
                    d['auto_generated_account'] = True
                    utils.update_persistent_data(d)
                    G.AUTO_GENERATED_ACCOUNT = True
                    editor.open_file(p)
                else:
                    editor.error_message('Something went wrong. You will need to sign up for an account to use Floobits.')
                    api.send_error('No username or secret')
            except Exception as e:
                msg.debug(traceback.format_exc())
                msg.error(str_e(e))
            try:
                d = utils.get_persistent_data()
                d['disable_account_creation'] = True
                utils.update_persistent_data(d)
            finally:
                self.proto.stop()

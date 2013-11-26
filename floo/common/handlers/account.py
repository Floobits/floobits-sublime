import os
import sys
import getpass

try:
    from . import base
    from .. import msg, api, shared as G, utils
    from ....floo import editor
    from ..protocols import floo_proto
    assert api and G and msg and utils
except (ImportError, ValueError):
    import base
    from floo import editor
    from floo.common.protocols import floo_proto
    from .. import msg, api, shared as G, utils

welcome_text = 'Welcome %s!\n\nYou\'re all set to collaborate. You should check out our docs at https://%s/help/plugins/#sublime-usage. \
You must run \'Floobits - Complete Sign Up\' in the command palette before you can login to floobits.com.'


class CreateAccountHandler(base.BaseHandler):
    PROTOCOL = floo_proto.FlooProtocol

    def on_connect(self):
        try:
            username = getpass.getuser()
        except:
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
                floorc = self.BASE_FLOORC + os.linesep.join(['%s %s' % (k, v) for k, v in data.items()]) + os.linesep
                with open(G.FLOORC_PATH, 'w') as floorc_fd:
                    floorc_fd.write(floorc)
                utils.reload_settings()
                if False in [bool(x) for x in (G.USERNAME, G.API_KEY, G.SECRET)]:
                    editor.message_dialog('Something went wrong. You will need to sign up for an account to use Floobits.')
                    api.send_error({'message': 'No username or secret'})
                else:
                    p = os.path.join(G.BASE_DIR, 'welcome.md')
                    with open(p, 'w') as fd:
                        text = welcome_text % (G.USERNAME, self.proto.host)
                        fd.write(text)
                    d = utils.get_persistent_data()
                    d['auto_generated_account'] = True
                    utils.update_persistent_data(d)
                    G.AUTO_GENERATED_ACCOUNT = True
                    editor.open_file(p)
            except Exception as e:
                msg.error(e)
            try:
                d = utils.get_persistent_data()
                d['disable_account_creation'] = True
                utils.update_persistent_data(d)
            finally:
                self.proto.stop()

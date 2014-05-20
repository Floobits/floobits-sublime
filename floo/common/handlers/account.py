import os
import sys
import traceback
import getpass
import json

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


class CreateAccountHandler(base.BaseHandler):
    PROTOCOL = floo_proto.FlooProtocol

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
                floo_json = {}
                floo_json['auth'] = {G.DEFAULT_HOST: data}
                with open(G.FLOOBITS_JSON_PATH, 'w') as fd:
                    data_as_string = json.dumps(floo_json, indent=4, sort_keys=True)
                    fd.write(data_as_string)
                utils.reload_settings(G.DEFAULT_HOST)
                if not utils.can_auth():
                    editor.error_message('Something went wrong. See https://%s/help/floorc to complete the installation.' % self.proto.host)
                    api.send_error('No username or secret')
                    return
                p = os.path.join(G.BASE_DIR, 'welcome.md')
                with open(p, 'w') as fd:
                    text = editor.welcome_text % (G.USERNAME, self.proto.host)
                    fd.write(text)
                d = utils.get_persistent_data()
                d['auto_generated_account'] = True
                utils.update_persistent_data(d)
                G.AUTO_GENERATED_ACCOUNT = True
                editor.open_file(p)
            except Exception as e:
                msg.debug(traceback.format_exc())
                msg.error(str(e))
                api.send_error(exception=e)

            try:
                d = utils.get_persistent_data()
                d['disable_account_creation'] = True
                utils.update_persistent_data(d)
            finally:
                self.proto.stop()

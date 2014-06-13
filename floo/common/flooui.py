import os.path
import webbrowser
import re
import json

try:
    from . import api, msg, utils, reactor, shared as G
    from .handlers import RequestCredentialsHandler, CreateAccountHandler
    from .. import editor
    from ..common.exc_fmt import str_e
except (ImportError, ValueError):
    from floo.common.exc_fmt import str_e
    from floo.common.handlers import RequestCredentialsHandler, CreateAccountHandler
    from floo.common import api, msg, utils, reactor, shared as G
    from floo import editor


class FlooUI(object):
    agent = None

    def __make_agent(self, owner, workspace, auth, created_workspace, d):
        """@returns new Agent()"""
        raise NotImplemented()

    def user_y_or_n(self, context, prompt, affirmation_txt, cb):
        """@returns True/False"""
        raise NotImplemented()

    def user_select(self, context, prompt, choices_big, choices_small, cb):
        """@returns (choice, index)"""
        raise NotImplemented()

    def user_charfield(self, context, prompt, initial, cb):
        """@returns String"""
        raise NotImplemented()

    def __handle_window(self, abs_path, cb):
        """opens a project in a window or something"""
        raise NotImplemented()

    @utils.inlined_callbacks
    def link_account(self, context, host, cb):
        prompt = 'No credentials found in ~/.floorc.json for %s.  Would you like to download them (opens a browser)?.' % host
        yes = yield self.user_y_or_n, context,  prompt, "Download"
        if not yes:
            return

        agent = RequestCredentialsHandler()
        if not agent:
            self.error_message('''A configuration error occured earlier. Please go to %s and sign up to use this plugin.\n
    We're really sorry. This should never happen.''' % host)
            return

        agent.once('end', cb)

        try:
            reactor.reactor.connect(agent, host, G.DEFAULT_PORT, True)
        except Exception as e:
            print(str_e(e))

    @utils.inlined_callbacks
    def create_or_link_account(self, context, host, cb):
        if host != "floobits.com":
            self.link_account(host, cb)
            return

        choices = [
            'Use an existing Floobits account',
            'Create a new Floobits account',
            'Cancel (see https://floobits.com/help/floorc)'
        ]

        (choice, index) = yield self.user_select, context, 'You need a Floobits account to use Floobits! Do you want to:', choices, None

        if index == -1:
            d = utils.get_persistent_data()
            if not d.get('disable_account_creation'):
                d['disable_account_creation'] = True
                utils.update_persistent_data(d)
                print('''You can set up a Floobits account at any time under\n\nTools -> Floobits -> Setup''')
            cb(None)
            return

        agent = None
        if index == 0:
            agent = RequestCredentialsHandler()
        else:
            agent = CreateAccountHandler()

        agent.once('end', cb)

        try:
            reactor.reactor.connect(agent, host, G.DEFAULT_PORT, True)
        except Exception as e:
            print(str_e(e))

    @utils.inlined_callbacks
    def remote_connect(self, context, host, owner, workspace, d, get_bufs=False):
        G.PROJECT_PATH = os.path.realpath(d)
        try:
            utils.mkdir(os.path.dirname(G.PROJECT_PATH))
        except Exception as e:
            msg.error("Couldn't create directory %s: %s" % (G.PROJECT_PATH, str_e(e)))
            return

        auth = G.AUTH.get(host)
        if not auth:
            success = yield self.link_account, context, host
            if not success:
                return
            auth = G.AUTH.get(host)
            if not auth:
                msg.error("Something went really wrong.")
                return
        if self.agent:
            try:
                self.agent.stop()
            except:
                pass

        self.agent = self.__make_agent(owner, workspace, self, auth, get_bufs and d)
        reactor.reactor.connect(self.agent, host, G.DEFAULT_PORT, True)
        url = self.agent.workspace_url
        utils.add_workspace_to_persistent_json(owner, workspace, url, d)
        utils.update_recent_workspaces(url)
        return self.agent

    @utils.inlined_callbacks
    def create_workspace(self, context, host, owner, name, perms, dir_to_share, cb):
        prompt = 'Workspace name: '

        api_args = {
            'name': name,
            'owner': owner,
        }

        if perms:
            api_args['perms'] = perms

        while True:
            new_name = yield self.user_charfield, context, prompt, name
            name = new_name or name
            try:
                api_args['name'] = name
                r = api.create_workspace(host, api_args)
            except Exception as e:
                msg.error('Unable to create workspace: %s' % str_e(e))
                editor.error_message('Unable to create workspace: %s' % str_e(e))
                return

            if r.code < 400:
                workspace_url = 'https://%s/%s/%s' % (host, owner, name)
                msg.log('Created workspace %s' % workspace_url)
                self.remote_connect(context, host, owner, name, dir_to_share, True)
                return

            msg.error('Unable to create workspace: %s' % r.body)

            if r.code not in (400, 402, 409):
                try:
                    r.body = r.body['detail']
                except Exception:
                    pass
                editor.error_message('Unable to create workspace: %s' % r.body)
                return

            if r.code == 402:
                try:
                    r.body = r.body['detail']
                except Exception:
                    pass

                yes = yield self.user_y_or_n, context, '%s Open billing settings?' % r.body, "Yes"
                if yes:
                    webbrowser.open('https://%s/%s/settings#billing' % (host, owner))
                return

            if r.code == 400:
                name = re.sub('[^A-Za-z0-9_\-\.]', '-', name)
                prompt = 'Invalid name. Workspace names must match the regex [A-Za-z0-9_\-\.]. Choose another name: '
                continue

            prompt = 'Workspace %s/%s already exists. Choose another name: ' % (owner, name)

    @utils.inlined_callbacks
    def join_workspace(self, context, host, name, owner, cwd=None, possible_dirs=None, line_endings=None):
        if line_endings is not None:
            editor.line_endings = line_endings.find("unix") >= 0 and "\n" or "\r\n"
        utils.reload_settings()

        if not utils.can_auth():
            success = yield self.create_or_link_account, context, host
            if not success:
                return
            utils.reload_settings()

        if cwd is not None:
            info = utils.read_floo_file(cwd)
            dot_floo_url = info and info.get('url')
            try:
                parsed_url = utils.parse_url(dot_floo_url)
            except Exception:
                parsed_url = None

            if parsed_url and parsed_url['host'] == host and parsed_url['workspace'] == name and parsed_url['owner'] == owner:
                self.remote_connect(context, host, owner, name, cwd)
                return

        try:
            d = utils.get_persistent_data()['workspaces'][owner][name]['path']
        except Exception:
            d = ''

        if os.path.isdir(d):
            self.remote_connect(context, host, owner, name, d)
            return

        possible_dirs = possible_dirs or []
        default_dir = None
        for d in possible_dirs:
            floo_file = os.path.join(d, '.floo')
            try:
                floo_info = open(floo_file, 'r').read()
                floorl = json.loads(floo_info).get('url')
                parsed_url = utils.parse_url(floorl)
                if parsed_url['host'] == host and parsed_url['workspace'] == name and parsed_url['owner'] == owner:
                    default_dir = d
                    break
            except Exception:
                pass

        d = default_dir or d or os.path.join(G.SHARE_DIR or G.BASE_DIR, owner, name)
        while True:
            d = yield self.user_charfield, context, 'Save workspace files to: ', d
            if not d:
                return
            d = os.path.realpath(os.path.expanduser(d))
            if not os.path.isdir(d):
                y_or_n = yield self.user_y_or_n, context, '%s is not a directory. Create it? ' % d, "Create Directory"
                if not y_or_n:
                    return
                utils.mkdir(d)
                if not os.path.isdir(d):
                    msg.error("Couldn't create directory %s" % d)
                    continue
            if os.path.isdir(d):
                self.remote_connect(context, host, owner, name, d)
                return

    @utils.inlined_callbacks
    def share_dir(self, context, dir_to_share, perms, line_endings=None):
        utils.reload_settings()
        if line_endings is not None:
            editor.line_endings = line_endings.find("unix") >= 0 and "\n" or "\r\n"
        dir_to_share = os.path.expanduser(dir_to_share)
        dir_to_share = utils.unfuck_path(dir_to_share)
        workspace_name = os.path.basename(dir_to_share)
        dir_to_share = os.path.realpath(dir_to_share)
        msg.debug('%s %s' % (workspace_name, dir_to_share))

        if not utils.can_auth():
            success = yield self.create_or_link_account, context, G.DEFAULT_HOST
            if not success:
                return
            utils.reload_settings()

        if os.path.isfile(dir_to_share):
            # file_to_share = dir_to_share
            dir_to_share = os.path.dirname(dir_to_share)

        try:
            utils.mkdir(dir_to_share)
        except Exception:
            msg.error("The directory %s doesn't exist and I can't create it." % dir_to_share)
            return

        info = utils.read_floo_file(dir_to_share)

        workspace_url = info.get('url')
        if workspace_url:
            try:
                parsed_url = api.prejoin_workspace(workspace_url, dir_to_share, {'perms': perms})
            except ValueError as e:
                pass
            if parsed_url:
                # TODO: make sure we create_flooignore
                # utils.add_workspace_to_persistent_json(parsed_url['owner'], parsed_url['workspace'], workspace_url, dir_to_share)
                self.remote_connect(context, parsed_url['host'], parsed_url['owner'], parsed_url['workspace'], dir_to_share)
                return

        def prejoin(workspace_url):
            try:
                return api.prejoin_workspace(workspace_url, dir_to_share, {'perms': perms})
            except ValueError:
                pass

        parsed_url = utils.get_workspace_by_path(dir_to_share, prejoin)
        if parsed_url:
            self.remote_connect(context, parsed_url['host'], parsed_url['owner'], parsed_url['workspace'], dir_to_share)
            return

        if not G.AUTH:
            return

        auths = dict(G.AUTH)
        hosts = list(auths.keys())
        if len(hosts) == 1:
            host = hosts[0]
        else:
            (host, index) = yield self.user_select, context, 'Which Floobits account should be used?', hosts, None
            if not host:
                return

        try:
            r = api.get_orgs_can_admin(host)
        except IOError as e:
            editor.error_message('Error getting org list: %s' % str_e(e))
            return

        choices = [G.AUTH[host]['username']]
        if r.code >= 400:
            editor.error_message('Error getting org list: %s' % r.body)
        elif r.body:
            choices += [org['name'] for org in r.body]

        if len(choices) == 1:
            owner = choices[0]
        else:
            owner = yield self.user_select, context, 'Create workspace owned by', choices, None

        yield self.create_workspace, host, owner, workspace_name, perms, dir_to_share

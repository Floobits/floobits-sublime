# coding: utf-8
import sys
import os
import re
import json
import uuid
import subprocess
import webbrowser

import sublime_plugin
import sublime

PY2 = sys.version_info < (3, 0)

try:
    from .floo import editor
    from .floo.sublime_connection import SublimeConnection
    from .floo.common import api, reactor, msg, shared as G, utils
    from .floo.common.exc_fmt import str_e
    from .floo.common.handlers.account import CreateAccountHandler
    from .floo.common.handlers.credentials import RequestCredentialsHandler
    assert api and G and msg and utils
except (ImportError, ValueError):
    from floo import editor
    from floo.common import api, reactor, msg, shared as G, utils
    from floo.common.exc_fmt import str_e
    from floo.common.handlers.account import CreateAccountHandler
    from floo.common.handlers.credentials import RequestCredentialsHandler
    from floo.sublime_connection import SublimeConnection

reactor = reactor.reactor


def disconnect_dialog():
    if G.AGENT and G.AGENT.joined_workspace:
        disconnect = sublime.ok_cancel_dialog('You can only be in one workspace at a time.', 'Leave %s/%s' % (G.AGENT.owner, G.AGENT.workspace))
        if disconnect:
            msg.debug('Stopping agent.')
            reactor.stop()
            G.AGENT = None
        return disconnect
    return True


def link_account(host, cb):
    account = sublime.ok_cancel_dialog('No credentials found in ~/.floorc.json for %s.\n\n'
                                       'Click "Link Account" to open a web browser and add credentials.' % host,
                                       'Link Account')
    if not account:
        return
    agent = RequestCredentialsHandler()
    if not agent:
        sublime.error_message('''A configuration error occured earlier. Please go to %s and sign up to use this plugin.\n
We're really sorry. This should never happen.''' % host)
        return

    agent.once('end', cb)

    try:
        reactor.connect(agent, host, G.DEFAULT_PORT, True)
    except Exception as e:
        print(str_e(e))


def create_or_link_account(force=False):
    disable_account_creation = utils.get_persistent_data().get('disable_account_creation')
    if disable_account_creation and not force:
        print('We could not automatically create or link your floobits account. Please go to floobits.com and sign up to use this plugin.')
        return

    opts = [
        ['Use existing Floobits account.', '(opens web page)'],
        ['Create a new Floobits account.', ''],
        ['Cancel', ''],
    ]

    def cb(index):
        if index == 0:
            agent = RequestCredentialsHandler()
        elif index == 1:
            agent = CreateAccountHandler()
        else:
            d = utils.get_persistent_data()
            if d.get('disable_account_creation'):
                return
            d['disable_account_creation'] = True
            utils.update_persistent_data(d)
            sublime.message_dialog('''You can set up a Floobits account at any time under\n\nTools -> Floobits -> Setup''')
        try:
            reactor.connect(agent, G.DEFAULT_HOST, G.DEFAULT_PORT, True)
        except Exception as e:
            print(str_e(e))

    def get_workspace_window():
        w = sublime.active_window()
        if w is None:
            return utils.set_timeout(get_workspace_window, 50)
        sublime.message_dialog('Thank you for installing the Floobits plugin!\n\nLet\'s set up your editor to work with Floobits.')
        w.show_quick_panel(opts, cb)
    get_workspace_window()


class FloobitsBaseCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return True

    def is_enabled(self):
        return bool(G.AGENT and G.AGENT.is_ready())


class FloobitsOpenSettingsCommand(sublime_plugin.WindowCommand):
    def run(self):
        window = sublime.active_window()
        if window:
            window.open_file(G.FLOORC_PATH)


class FloobitsShareDirCommand(FloobitsBaseCommand):
    def is_enabled(self):
        return not super(FloobitsShareDirCommand, self).is_enabled()

    def run(self, dir_to_share=None, paths=None, current_file=False, api_args=None):
        self.api_args = api_args
        utils.reload_settings()
        if not utils.can_auth():
            return create_or_link_account()
        if paths:
            if len(paths) != 1:
                return sublime.error_message('Only one folder at a time, please. :(')
            return self.on_input(paths[0])
        if dir_to_share is None:
            folders = self.window.folders()
            if folders:
                dir_to_share = folders[0]
            else:
                dir_to_share = os.path.expanduser(os.path.join('~', 'share_me'))
        self.window.show_input_panel('Directory to share:', dir_to_share, self.on_input, None, None)

    @utils.inlined_callbacks
    def on_input(self, dir_to_share):
        file_to_share = None
        dir_to_share = os.path.expanduser(dir_to_share)
        dir_to_share = os.path.realpath(utils.unfuck_path(dir_to_share))
        workspace_name = os.path.basename(dir_to_share)
        workspace_url = None

        # TODO: use prejoin_workspace instead
        def find_workspace(workspace_url):
            r = api.get_workspace_by_url(workspace_url)
            if r.code < 400:
                return r
            try:
                result = utils.parse_url(workspace_url)
                d = utils.get_persistent_data()
                del d['workspaces'][result['owner']][result['name']]
                utils.update_persistent_data(d)
            except Exception as e:
                msg.debug(str_e(e))

        def join_workspace(workspace_url):
            try:
                w = find_workspace(workspace_url)
            except Exception as e:
                sublime.error_message('Error: %s' % str_e(e))
                return False
            if not w:
                return False
            msg.debug('workspace: %s', json.dumps(w.body))
            # if self.api_args:
            anon_perms = w.body.get('perms', {}).get('AnonymousUser', [])
            new_anon_perms = self.api_args.get('perms').get('AnonymousUser', [])
            # TODO: warn user about making a private workspace public
            if set(anon_perms) != set(new_anon_perms):
                msg.debug(str(anon_perms), str(new_anon_perms))
                w.body['perms']['AnonymousUser'] = new_anon_perms
                response = api.update_workspace(workspace_url, w.body)
                msg.debug(str(response.body))
            utils.add_workspace_to_persistent_json(w.body['owner'], w.body['name'], workspace_url, dir_to_share)
            self.window.run_command('floobits_join_workspace', {'workspace_url': workspace_url})
            return True

        if os.path.isfile(dir_to_share):
            file_to_share = dir_to_share
            dir_to_share = os.path.dirname(dir_to_share)

        try:
            utils.mkdir(dir_to_share)
        except Exception:
            sublime.error_message('The directory %s doesn\'t exist and I can\'t create it.' % dir_to_share)
            return

        floo_file = os.path.join(dir_to_share, '.floo')

        info = {}
        try:
            floo_info = open(floo_file, 'r').read()
            info = json.loads(floo_info)
        except (IOError, OSError):
            pass
        except Exception:
            msg.error('Couldn\'t read the floo_info file: %s' % floo_file)

        workspace_url = info.get('url')
        try:
            utils.parse_url(workspace_url)
        except Exception:
            workspace_url = None

        if workspace_url and join_workspace(workspace_url):
            return

        for owner, workspaces in utils.get_persistent_data()['workspaces'].items():
            for name, workspace in workspaces.items():
                if workspace['path'] == dir_to_share:
                    workspace_url = workspace['url']
                    if join_workspace(workspace_url):
                        return

        auth = yield editor.select_auth, self.window, G.AUTH
        if not auth:
            return

        username = auth.get('username')
        host = auth['host']

        def on_done(owner):
            msg.log('Colab dir: %s, Username: %s, Workspace: %s/%s' % (G.COLAB_DIR, username, owner[0], workspace_name))
            self.window.run_command('floobits_create_workspace', {
                'workspace_name': workspace_name,
                'dir_to_share': dir_to_share,
                'upload': file_to_share or dir_to_share,
                'api_args': self.api_args,
                'owner': owner[0],
                'host': host,
            })

        try:
            r = api.get_orgs_can_admin(host)
        except IOError as e:
            sublime.error_message('Error getting org list: %s' % str_e(e))
            return

        if r.code >= 400 or len(r.body) == 0:
            on_done([username])
            return

        orgs = [[org['name'], 'Create workspace owned by %s' % org['name']] for org in r.body]
        orgs.insert(0, [username, 'Create workspace owned by %s' % username])
        self.window.show_quick_panel(orgs, lambda index: index < 0 or on_done(orgs[index]))


class FloobitsCreateWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    # TODO: throw workspace_name in api_args
    def run(self, workspace_name=None, dir_to_share=None, prompt='Workspace name:', api_args=None, owner=None, upload=None, host=None):
        if not disconnect_dialog():
            return
        self.owner = owner
        self.dir_to_share = dir_to_share
        self.workspace_name = workspace_name
        self.api_args = api_args or {}
        self.upload = upload
        self.host = host
        if workspace_name and dir_to_share and prompt == 'Workspace name:':
            return self.on_input(workspace_name, dir_to_share)
        self.window.show_input_panel(prompt, workspace_name, self.on_input, None, None)

    def on_input(self, workspace_name, dir_to_share=None):
        if dir_to_share:
            self.dir_to_share = dir_to_share
        if workspace_name == '':
            return self.run(dir_to_share=self.dir_to_share)
        try:
            self.api_args['name'] = workspace_name
            self.api_args['owner'] = self.owner
            msg.debug(str(self.api_args))
            r = api.create_workspace(self.host, self.api_args)
        except Exception as e:
            msg.error('Unable to create workspace: %s' % str_e(e))
            return sublime.error_message('Unable to create workspace: %s' % str_e(e))

        workspace_url = 'https://%s/%s/%s' % (self.host, self.owner, workspace_name)
        msg.log('Created workspace %s' % workspace_url)

        if r.code < 400:
            utils.add_workspace_to_persistent_json(self.owner, workspace_name, workspace_url, self.dir_to_share)
            return self.window.run_command('floobits_join_workspace', {
                'workspace_url': workspace_url,
                'upload': dir_to_share
            })

        msg.error('Unable to create workspace: %s' % r.body)
        if r.code not in [400, 402, 409]:
            try:
                r.body = r.body['detail']
            except Exception:
                pass
            return sublime.error_message('Unable to create workspace: %s' % r.body)

        kwargs = {
            'dir_to_share': self.dir_to_share,
            'workspace_name': workspace_name,
            'api_args': self.api_args,
            'owner': self.owner,
            'upload': self.upload,
            'host': self.host,
        }
        if r.code == 400:
            kwargs['workspace_name'] = re.sub('[^A-Za-z0-9_\-\.]', '-', workspace_name)
            kwargs['prompt'] = 'Invalid name. Workspace names must match the regex [A-Za-z0-9_\-\.]. Choose another name:'
        elif r.code == 402:
            try:
                r.body = r.body['detail']
            except Exception:
                pass
            if sublime.ok_cancel_dialog('%s' % r.body, 'Open billing settings'):
                webbrowser.open('https://%s/%s/settings#billing' % (self.host, self.owner))
            return
        else:
            kwargs['prompt'] = 'Workspace %s/%s already exists. Choose another name:' % (self.owner, workspace_name)

        return self.window.run_command('floobits_create_workspace', kwargs)


class FloobitsPromptJoinWorkspaceCommand(sublime_plugin.WindowCommand):

    def run(self, workspace=None):
        if workspace is None:
            workspace = 'https://%s/' % G.DEFAULT_HOST
        for d in self.window.folders():
            floo_file = os.path.join(d, '.floo')
            try:
                floo_info = open(floo_file, 'r').read()
                wurl = json.loads(floo_info).get('url')
                utils.parse_url(wurl)
                # TODO: check if workspace actually exists
                workspace = wurl
                break
            except Exception:
                pass
        self.window.show_input_panel('Workspace URL:', workspace, self.on_input, None, None)

    def on_input(self, workspace_url):
        if disconnect_dialog():
            self.window.run_command('floobits_join_workspace', {
                'workspace_url': workspace_url,
            })


class FloobitsJoinWorkspaceCommand(sublime_plugin.WindowCommand):

    def run(self, workspace_url, agent_conn_kwargs=None, upload=None):
        agent_conn_kwargs = agent_conn_kwargs or {}
        self.upload = upload

        def get_workspace_window():
            workspace_window = None
            for w in sublime.windows():
                for f in w.folders():
                    if utils.unfuck_path(f) == utils.unfuck_path(G.PROJECT_PATH):
                        workspace_window = w
                        break
            return workspace_window

        def set_workspace_window(cb):
            workspace_window = get_workspace_window()
            if workspace_window is None:
                return utils.set_timeout(set_workspace_window, 50, cb)
            G.WORKSPACE_WINDOW = workspace_window
            cb()

        def open_workspace_window(cb):
            if PY2:
                open_workspace_window2(cb)
            else:
                open_workspace_window3(cb)

        def open_workspace_window2(cb):
            if sublime.platform() == 'linux':
                subl = open('/proc/self/cmdline').read().split(chr(0))[0]
            elif sublime.platform() == 'osx':
                floorc = utils.load_floorc_json()
                subl = floorc.get('SUBLIME_EXECUTABLE')
                if not subl:
                    settings = sublime.load_settings('Floobits.sublime-settings')
                    subl = settings.get('sublime_executable', '/Applications/Sublime Text 2.app/Contents/SharedSupport/bin/subl')
                if not os.path.exists(subl):
                    return sublime.error_message('''Can't find your Sublime Text executable at %s.
Please add "sublime_executable": "/path/to/subl" to your ~/.floorc.json and restart Sublime Text''' % subl)
            elif sublime.platform() == 'windows':
                subl = sys.executable
            else:
                raise Exception('WHAT PLATFORM ARE WE ON?!?!?')

            command = [subl]
            if get_workspace_window() is None:
                command.append('--new-window')
            command.append('--add')
            command.append(G.PROJECT_PATH)

            msg.debug('command:', command)
            p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            poll_result = p.poll()
            msg.debug('poll:', poll_result)

            set_workspace_window(cb)

        def open_workspace_window3(cb):
            def finish(w):
                G.WORKSPACE_WINDOW = w
                msg.debug('Setting project data. Path: %s' % G.PROJECT_PATH)
                G.WORKSPACE_WINDOW.set_project_data({'folders': [{'path': G.PROJECT_PATH}]})
                cb()

            def get_empty_window():
                for w in sublime.windows():
                    project_data = w.project_data()
                    try:
                        folders = project_data.get('folders', [])
                        if len(folders) == 0 or not folders[0].get('path'):
                            # no project data. co-opt this window
                            return w
                    except Exception as e:
                        print(str_e(e))

            def wait_empty_window(i):
                if i > 10:
                    print('Too many failures trying to find an empty window. Using active window.')
                    return finish(sublime.active_window())
                w = get_empty_window()
                if w:
                    return finish(w)
                return utils.set_timeout(wait_empty_window, 50, i + 1)

            w = get_workspace_window() or get_empty_window()
            if w:
                return finish(w)

            sublime.run_command('new_window')
            wait_empty_window(0)

        def make_dir(d):
            d = os.path.realpath(os.path.expanduser(d))

            if not os.path.isdir(d):
                make_dir = sublime.ok_cancel_dialog('%s is not a directory. Create it?' % d)
                if not make_dir:
                    return self.window.show_input_panel('%s is not a directory. Enter an existing path:' % d, d, None, None, None)
                try:
                    utils.mkdir(d)
                except Exception as e:
                    return sublime.error_message('Could not create directory %s: %s' % (d, str_e(e)))
            G.PROJECT_PATH = d

            if self.upload:
                result['upload'] = d
            else:
                result['upload'] = ""

            utils.add_workspace_to_persistent_json(result['owner'], result['workspace'], workspace_url, d)
            open_workspace_window(lambda: run_agent(**result))

        @utils.inlined_callbacks
        def run_agent(owner, workspace, host, port, secure, upload):
            if G.AGENT:
                msg.debug('Stopping agent.')
                reactor.stop()
                G.AGENT = None
            try:
                auth = G.AUTH.get(host)
                if not auth:
                    success = yield link_account, host
                    if not success:
                        return
                    auth = G.AUTH.get(host)
                conn = SublimeConnection(owner, workspace, auth, upload)
                reactor.connect(conn, host, port, secure)
            except Exception as e:
                msg.error(str_e(e))

        try:
            result = utils.parse_url(workspace_url)
        except Exception as e:
            return sublime.error_message(str_e(e))

        utils.reload_settings()
        if not utils.can_auth():
            return create_or_link_account()

        d = utils.get_persistent_data()
        try:
            G.PROJECT_PATH = d['workspaces'][result['owner']][result['workspace']]['path']
        except Exception:
            msg.log('%s/%s not in persistent.json' % (result['owner'], result['workspace']))
            G.PROJECT_PATH = ''

        msg.log('Project path is %s' % G.PROJECT_PATH)

        if not os.path.isdir(G.PROJECT_PATH):
            default_dir = None
            for w in sublime.windows():
                if default_dir:
                    break
                for d in self.window.folders():
                    floo_file = os.path.join(d, '.floo')
                    try:
                        floo_info = open(floo_file, 'r').read()
                        wurl = json.loads(floo_info).get('url')
                        if wurl == workspace_url:
                            # TODO: check if workspace actually exists
                            default_dir = d
                            break
                    except Exception:
                        pass

            default_dir = default_dir or os.path.realpath(os.path.join(G.COLAB_DIR, result['owner'], result['workspace']))

            return self.window.show_input_panel('Save workspace in directory:', default_dir, make_dir, None, None)

        open_workspace_window(lambda: run_agent(upload=upload, **result))


class FloobitsPinocchioCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return G.AUTO_GENERATED_ACCOUNT

    def run(self):
        floorc = utils.load_floorc_json()
        auth = floorc.get('AUTH', {}).get(G.DEFAULT_HOST, {})
        username = auth.get('username')
        secret = auth.get('secret')
        print(username, secret)
        if not (username and secret):
            return sublime.error_message('You don\'t seem to have a Floobits account of any sort')
        webbrowser.open('https://%s/%s/pinocchio/%s' % (G.DEFAULT_HOST, username, secret))


class FloobitsLeaveWorkspaceCommand(FloobitsBaseCommand):

    def run(self):
        if G.AGENT:
            message = 'You have left the workspace.'
            G.AGENT.update_status_msg(message)
            reactor.stop()
            G.AGENT = None
            # TODO: Mention the name of the thing we left
            if not G.EXPERT_MODE:
                sublime.error_message(message)
        else:
            sublime.error_message('You are not joined to any workspace.')

    def is_enabled(self):
        return bool(G.AGENT)


class FloobitsClearHighlightsCommand(FloobitsBaseCommand):
    def run(self):
        G.AGENT.clear_highlights(self.window.active_view())


class FloobitsSummonCommand(FloobitsBaseCommand):
    # TODO: ghost this option if user doesn't have permissions
    def run(self):
        G.AGENT.summon(self.window.active_view())


class FloobitsJoinRecentWorkspaceCommand(sublime_plugin.WindowCommand):
    def _get_recent_workspaces(self):
        self.recent_workspaces = utils.get_persistent_data()['recent_workspaces']

        try:
            recent_workspaces = [x.get('url') for x in self.recent_workspaces if x.get('url') is not None]
        except Exception:
            pass
        return recent_workspaces

    def run(self, *args):
        workspaces = self._get_recent_workspaces()
        self.window.show_quick_panel(workspaces, self.on_done)

    def on_done(self, item):
        if item == -1:
            return
        workspace = self.recent_workspaces[item]
        if disconnect_dialog():
            self.window.run_command('floobits_join_workspace', {'workspace_url': workspace['url']})

    def is_enabled(self):
        return bool(len(self._get_recent_workspaces()) > 0)


class FloobitsAddToWorkspaceCommand(FloobitsBaseCommand):
    def run(self, paths, current_file=False):
        if not self.is_enabled():
            return

        if paths is None and current_file:
            paths = [self.window.active_view().file_name()]

        notshared = []
        for path in paths:
            if utils.is_shared(path):
                G.AGENT.upload(path)
            else:
                notshared.append(path)

        if notshared:
            limit = 5
            sublime.error_message("The following paths are not a child of\n\n%s\n\nand will not be shared for security reasons:\n\n%s%s." %
                                  (G.PROJECT_PATH, ",\n".join(notshared[:limit]), len(notshared) > limit and ",\n..." or ""))

    def description(self):
        return 'Add file or directory to currently-joined Floobits workspace.'


class FloobitsRemoveFromWorkspaceCommand(FloobitsBaseCommand):
    def run(self, paths, current_file=False):
        if not self.is_enabled():
            return

        unlink = bool(sublime.ok_cancel_dialog('Delete? Hit cancel to remove from the workspace without deleting.', 'Delete'))

        if paths is None and current_file:
            paths = [self.window.active_view().file_name()]

        for path in paths:
            G.AGENT.delete_buf(path, unlink)

    def description(self):
        return 'Add file or directory to currently-joined Floobits workspace.'


class FloobitsCreateHangoutCommand(FloobitsBaseCommand):
    def run(self):
        owner = G.AGENT.owner
        workspace = G.AGENT.workspace
        host = G.AGENT.proto.host
        webbrowser.open('https://plus.google.com/hangouts/_?gid=770015849706&gd=%s/%s/%s' % (host, owner, workspace))

    def is_enabled(self):
        return bool(super(FloobitsCreateHangoutCommand, self).is_enabled() and G.AGENT.owner and G.AGENT.workspace)


class FloobitsPromptHangoutCommand(FloobitsBaseCommand):
    def run(self, hangout_url):
        confirm = bool(sublime.ok_cancel_dialog('This workspace is being edited in a Google+ Hangout? Do you want to join the hangout?'))
        if not confirm:
            return
        webbrowser.open(hangout_url)

    def is_visible(self):
        return False

    def is_enabled(self):
        return bool(super(FloobitsPromptHangoutCommand, self).is_enabled() and G.AGENT.owner and G.AGENT.workspace)


class FloobitsOpenWebEditorCommand(FloobitsBaseCommand):
    def run(self):
        try:
            agent = G.AGENT
            url = utils.to_workspace_url({
                'port': agent.proto.port,
                'secure': agent.proto.secure,
                'owner': agent.owner,
                'workspace': agent.workspace,
                'host': agent.proto.host,
            })
            webbrowser.open(url)
        except Exception as e:
            sublime.error_message('Unable to open workspace in web editor: %s' % str_e(e))


class FloobitsHelpCommand(FloobitsBaseCommand):
    def run(self):
        webbrowser.open('https://floobits.com/help/plugins/sublime', new=2, autoraise=True)

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


class FloobitsToggleFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        if G.FOLLOW_MODE:
            self.window.run_command('floobits_disable_follow_mode')
        else:
            self.window.run_command('floobits_enable_follow_mode')


class FloobitsEnableFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        G.FOLLOW_MODE = True
        msg.log('Follow mode enabled')
        G.AGENT.update_status_msg()
        G.AGENT.highlight()

    def is_visible(self):
        if G.AGENT:
            return self.is_enabled()
        return True

    def is_enabled(self):
        return bool(super(FloobitsEnableFollowModeCommand, self).is_enabled() and not G.FOLLOW_MODE)


class FloobitsDisableFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        G.FOLLOW_MODE = False
        G.SPLIT_MODE = False
        msg.log('Follow mode disabled')
        G.AGENT.update_status_msg('Stopped following changes. ')

    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return bool(super(FloobitsDisableFollowModeCommand, self).is_enabled() and G.FOLLOW_MODE)


class FloobitsOpenWorkspaceSettingsCommand(FloobitsBaseCommand):
    def run(self):
        url = G.AGENT.workspace_url + '/settings'
        webbrowser.open(url, new=2, autoraise=True)

    def is_enabled(self):
        return bool(super(FloobitsOpenWorkspaceSettingsCommand, self).is_enabled() and G.PERMS and 'kick' in G.PERMS)


class RequestPermissionCommand(FloobitsBaseCommand):
    def run(self, perms, *args, **kwargs):
        G.AGENT.send({
            'name': 'request_perms',
            'perms': perms
        })

    def is_enabled(self):
        if not super(RequestPermissionCommand, self).is_enabled():
            return False
        if 'patch' in G.PERMS:
            return False
        return True


class FloobitsFollowSplit(FloobitsBaseCommand):
    def run(self):
        G.SPLIT_MODE = True
        G.FOLLOW_MODE = True
        if self.window.num_groups() == 1:
            self.window.set_layout({
                'cols': [0.0, 1.0],
                'rows': [0.0, 0.5, 1.0],
                'cells': [[0, 0, 1, 1], [0, 1, 1, 2]]
            })


class FloobitsSetup(FloobitsBaseCommand):
    def is_visible(self):
        return True

    def is_enabled(self):
        return not utils.can_auth()

    def run(self):
        create_or_link_account(True)


class FloobitsNotACommand(sublime_plugin.WindowCommand):
    def run(self, *args, **kwargs):
        pass

    def is_visible(self):
        return True

    def is_enabled(self):
        return False

    def description(self):
        return

# coding: utf-8
try:
    unicode()
except NameError:
    unicode = str

import sys
import os
import re
import hashlib
import json
import uuid
import binascii
import subprocess
import traceback
import webbrowser
import threading

import sublime_plugin
import sublime

PY2 = sys.version_info < (3, 0)


if PY2 and sublime.platform() == 'windows':
    err_msg = '''Sorry, but the Windows version of Sublime Text 2 lacks Python's select module, so the Floobits plugin won't work.
Please upgrade to Sublime Text 3. :('''
    raise(Exception(err_msg))
elif sublime.platform() == 'osx':
    try:
        p = subprocess.Popen(['/usr/bin/sw_vers', '-productVersion'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = p.communicate()
        if float(result[0][:4]) < 10.7:
            sublime.error_message('''Sorry, but the Floobits plugin doesn\'t work on 10.6 or earlier.
Please upgrade your operating system if you want to use this plugin. :(''')
    except Exception as e:
        print(e)

try:
    from .floo import version
    from .floo import sublime_utils as sutils
    from .floo.listener import Listener
    from .floo.sublime_connection import SublimeConnection
    from .floo.common import api, ignore, reactor, msg, shared as G, utils
    from .floo.common.handlers.account import CreateAccountHandler
    from .floo.common.handlers.credentials import RequestCredentialsHandler
    assert api and G and ignore and msg and utils
except (ImportError, ValueError):
    from floo import version
    from floo import sublime_utils as sutils
    from floo.listener import Listener
    from floo.common import api, ignore, reactor, msg, shared as G, utils
    from floo.common.handlers.account import CreateAccountHandler
    from floo.common.handlers.credentials import RequestCredentialsHandler
    from floo.sublime_connection import SublimeConnection

assert Listener and version

reactor = reactor.reactor

on_room_info_waterfall = utils.Waterfall()
ignore_modified_timeout = None


def update_recent_workspaces(workspace):
    d = utils.get_persistent_data()
    recent_workspaces = d.get('recent_workspaces', [])
    recent_workspaces.insert(0, workspace)
    recent_workspaces = recent_workspaces[:100]
    seen = set()
    new = []
    for r in recent_workspaces:
        string = json.dumps(r)
        if string not in seen:
            new.append(r)
            seen.add(string)
    d['recent_workspaces'] = new
    utils.update_persistent_data(d)


def ssl_error_msg(action):
    sublime.error_message('Your version of Sublime Text can\'t ' + action + ' because it has a broken SSL module. '
                          'This is a known issue on Linux builds of Sublime Text. '
                          'See this issue: https://github.com/SublimeText/Issues/issues/177')


def get_active_window(cb):
    win = sublime.active_window()
    if not win:
        return utils.set_timeout(get_active_window, 50, cb)
    cb(win)


def create_or_link_account():
    agent = None
    account = sublime.ok_cancel_dialog('You need a Floobits account!\n\n'
                                       'Click "Open browser" if you have one or click "cancel" and we\'ll make it for you.',
                                       'Open browser')
    if account:
        token = binascii.b2a_hex(uuid.uuid4().bytes).decode('utf-8')
        agent = RequestCredentialsHandler(token)
    elif utils.get_persistent_data().get('disable_account_creation'):
        print('persistent.json has disable_account_creation. Skipping CreateAccountHandler')
    else:
        agent = CreateAccountHandler()

    if not agent:
        sublime.error_message('''A configuration error occured earlier. Please go to floobits.com and sign up to use this plugin.\n
We're really sorry. This should never happen.''')
        return

    try:
        reactor.connect(agent, G.DEFAULT_HOST, G.DEFAULT_PORT, True)
    except Exception as e:
        print(e)
        tb = traceback.format_exc()
        print(tb)


def global_tick():
    reactor.tick()
    utils.set_timeout(global_tick, G.TICK_TIME)


def disconnect_dialog():
    if G.AGENT and G.AGENT.joined_workspace:
        disconnect = sublime.ok_cancel_dialog('You can only be in one workspace at a time.', 'Leave %s/%s' % (G.AGENT.owner, G.AGENT.workspace))
        if disconnect:
            msg.debug('Stopping agent.')
            reactor.stop()
            G.AGENT = None
        return disconnect
    return True


def on_room_info_msg():
    who = 'Your friends'
    anon_perms = G.AGENT.workspace_info.get('anon_perms')
    if 'get_buf' in anon_perms:
        who = 'Anyone'
    _msg = 'You are sharing:\n\n%s\n\n%s can join your workspace at:\n\n%s' % (G.PROJECT_PATH, who, G.AGENT.workspace_url)
    # Workaround for horrible Sublime Text bug
    utils.set_timeout(sublime.message_dialog, 0, _msg)


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
        global on_room_info_waterfall
        self.api_args = api_args
        utils.reload_settings()
        if not (G.USERNAME and G.SECRET):
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
        on_room_info_waterfall = utils.Waterfall()
        self.window.show_input_panel('Directory to share:', dir_to_share, self.on_input, None, None)

    def on_input(self, dir_to_share):
        file_to_share = None
        dir_to_share = os.path.expanduser(dir_to_share)
        dir_to_share = os.path.realpath(utils.unfuck_path(dir_to_share))
        workspace_name = os.path.basename(dir_to_share)
        workspace_url = None
        print(G.COLAB_DIR, G.USERNAME, workspace_name)

        def find_workspace(workspace_url):
            r = api.get_workspace_by_url(workspace_url)
            if r.code < 400:
                on_room_info_waterfall.add(ignore.create_flooignore, dir_to_share)
                on_room_info_waterfall.add(lambda: G.AGENT.upload(dir_to_share, on_room_info_msg))
                return r
            try:
                result = utils.parse_url(workspace_url)
                d = utils.get_persistent_data()
                del d['workspaces'][result['owner']][result['name']]
                utils.update_persistent_data(d)
            except Exception as e:
                msg.debug(unicode(e))
            return

        def join_workspace(workspace_url):
            try:
                w = find_workspace(workspace_url)
            except Exception as e:
                sublime.error_message('Error: %s' % str(e))
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
                response = api.update_workspace(w.body['owner'], w.body['name'], w.body)
                msg.debug(str(response.body))
            utils.add_workspace_to_persistent_json(w.body['owner'], w.body['name'], workspace_url, dir_to_share)
            self.window.run_command('floobits_join_workspace', {
                'workspace_url': workspace_url,
                'agent_conn_kwargs': {'get_bufs': False}})
            return True

        if os.path.isfile(dir_to_share):
            file_to_share = dir_to_share
            dir_to_share = os.path.dirname(dir_to_share)

        try:
            utils.mkdir(dir_to_share)
        except Exception:
            return sublime.error_message('The directory %s doesn\'t exist and I can\'t create it.' % dir_to_share)

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

        # make & join workspace
        on_room_info_waterfall.add(ignore.create_flooignore, dir_to_share)
        on_room_info_waterfall.add(lambda: G.AGENT.upload(file_to_share or dir_to_share, on_room_info_msg))

        def on_done(owner):
            self.window.run_command('floobits_create_workspace', {
                'workspace_name': workspace_name,
                'dir_to_share': dir_to_share,
                'api_args': self.api_args,
                'owner': owner[0],
            })

        try:
            r = api.get_orgs_can_admin()
        except IOError as e:
            return sublime.error_message('Error getting org list: %s' % str(e))

        if r.code >= 400 or len(r.body) == 0:
            return on_done([G.USERNAME])

        orgs = [[org['name'], 'Create workspace owned by %s' % org['name']] for org in r.body]
        orgs.insert(0, [G.USERNAME, 'Create workspace owned by %s' % G.USERNAME])
        self.window.show_quick_panel(orgs, lambda index: index < 0 or on_done(orgs[index]))


class FloobitsCreateWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    # TODO: throw workspace_name in api_args
    def run(self, workspace_name=None, dir_to_share=None, prompt='Workspace name:', api_args=None, owner=None):
        if not disconnect_dialog():
            return
        self.owner = owner or G.USERNAME
        self.dir_to_share = dir_to_share
        self.workspace_name = workspace_name
        self.api_args = api_args or {}
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
            r = api.create_workspace(self.api_args)
        except Exception as e:
            msg.error('Unable to create workspace: %s' % unicode(e))
            return sublime.error_message('Unable to create workspace: %s' % unicode(e))

        workspace_url = 'https://%s/%s/%s' % (G.DEFAULT_HOST, self.owner, workspace_name)
        msg.log('Created workspace %s' % workspace_url)

        if r.code < 400:
            utils.add_workspace_to_persistent_json(self.owner, workspace_name, workspace_url, self.dir_to_share)
            return self.window.run_command('floobits_join_workspace', {
                'workspace_url': workspace_url,
                'agent_conn_kwargs': {
                    'get_bufs': False
                }
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
                webbrowser.open('https://%s/%s/settings#billing' % (G.DEFAULT_HOST, self.owner))
            return
        else:
            kwargs['prompt'] = 'Workspace %s/%s already exists. Choose another name:' % (self.owner, workspace_name)

        return self.window.run_command('floobits_create_workspace', kwargs)


class FloobitsPromptJoinWorkspaceCommand(sublime_plugin.WindowCommand):

    def run(self, workspace='https://floobits.com/'):
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

    def run(self, workspace_url, agent_conn_kwargs=None):
        agent_conn_kwargs = agent_conn_kwargs or {}

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
                floorc = utils.load_floorc()
                subl = floorc.get('SUBLIME_EXECUTABLE')
                if not subl:
                    settings = sublime.load_settings('Floobits.sublime-settings')
                    subl = settings.get('sublime_executable', '/Applications/Sublime Text 2.app/Contents/SharedSupport/bin/subl')
                if not os.path.exists(subl):
                    return sublime.error_message('''Can't find your Sublime Text executable at %s.
Please add "sublime_executable /path/to/subl" to your ~/.floorc and restart Sublime Text''' % subl)
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
                        print(e)

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
                    return sublime.error_message('Could not create directory %s: %s' % (d, str(e)))

            G.PROJECT_PATH = d
            utils.add_workspace_to_persistent_json(result['owner'], result['workspace'], workspace_url, d)
            open_workspace_window(lambda: run_agent(**result))

        def run_agent(owner, workspace, host, port, secure):
            global on_room_info_waterfall
            if G.AGENT:
                msg.debug('Stopping agent.')
                reactor.stop()
                G.AGENT = None
            on_room_info_waterfall.add(update_recent_workspaces, {'url': workspace_url})
            try:
                conn = SublimeConnection(owner, workspace, agent_conn_kwargs.get('get_bufs', True))
                reactor.connect(conn, host, port, secure)
                conn.once('room_info', on_room_info_waterfall.call)
                on_room_info_waterfall = utils.Waterfall()
            except Exception as e:
                print(e)
                tb = traceback.format_exc()
                print(tb)

        try:
            result = utils.parse_url(workspace_url)
        except Exception as e:
            return sublime.error_message(str(e))

        utils.reload_settings()
        if not (G.USERNAME and G.SECRET):
            return create_or_link_account()

        d = utils.get_persistent_data()
        try:
            G.PROJECT_PATH = d['workspaces'][result['owner']][result['workspace']]['path']
        except Exception as e:
            G.PROJECT_PATH = ''

        print('Project path is %s' % G.PROJECT_PATH)

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

        open_workspace_window(lambda: run_agent(**result))


class FloobitsPinocchioCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return G.AUTO_GENERATED_ACCOUNT

    def run(self):
        floorc = utils.load_floorc()
        username = floorc.get('USERNAME')
        secret = floorc.get('SECRET')
        print(username, secret)
        if not (username and secret):
            return sublime.error_message('You don\'t seem to have a Floobits account of any sort')
        webbrowser.open('https://%s/%s/pinocchio/%s' % (G.DEFAULT_HOST, username, secret))


class FloobitsLeaveWorkspaceCommand(FloobitsBaseCommand):

    def run(self):
        if G.AGENT:
            reactor.stop()
            G.AGENT = None
            # TODO: Mention the name of the thing we left
            sublime.error_message('You have left the workspace.')
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
        webbrowser.open('https://plus.google.com/hangouts/_?gid=770015849706&gd=%s/%s' % (owner, workspace))

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
            sublime.error_message('Unable to open workspace in web editor: %s' % unicode(e))


class FloobitsHelpCommand(FloobitsBaseCommand):
    def run(self):
        webbrowser.open('https://floobits.com/help/plugins/sublime', new=2, autoraise=True)

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


class FloobitsToggleStalkerModeCommand(FloobitsBaseCommand):
    def run(self):
        if G.STALKER_MODE:
            self.window.run_command('floobits_disable_stalker_mode')
        else:
            self.window.run_command('floobits_enable_stalker_mode')


class FloobitsEnableStalkerModeCommand(FloobitsBaseCommand):
    def run(self):
        G.STALKER_MODE = True
        msg.log('Stalker mode enabled')
        G.AGENT.update_status_msg()
        G.AGENT.highlight()

    def is_visible(self):
        if G.AGENT:
            return self.is_enabled()
        return True

    def is_enabled(self):
        return bool(super(FloobitsEnableStalkerModeCommand, self).is_enabled() and not G.STALKER_MODE)


class FloobitsDisableStalkerModeCommand(FloobitsBaseCommand):
    def run(self):
        G.STALKER_MODE = False
        G.SPLIT_MODE = False
        msg.log('Stalker mode disabled')
        G.AGENT.update_status_msg('Stopped following changes. ')

    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return bool(super(FloobitsDisableStalkerModeCommand, self).is_enabled() and G.STALKER_MODE)


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
        G.STALKER_MODE = True
        if self.window.num_groups() == 1:
            self.window.set_layout({
                'cols': [0.0, 1.0],
                'rows': [0.0, 0.5, 1.0],
                'cells': [[0, 0, 1, 1], [0, 1, 1, 2]]
            })


class FloobitsNotACommand(sublime_plugin.WindowCommand):
    def run(self, *args, **kwargs):
        pass

    def is_visible(self):
        return True

    def is_enabled(self):
        return False

    def description(self):
        return


def unignore_modified_events():
    G.IGNORE_MODIFIED_EVENTS = False


def transform_selections(selections, start, new_offset):
    new_sels = []
    for sel in selections:
        a = sel.a
        b = sel.b
        if sel.a > start:
            a += new_offset
        if sel.b > start:
            b += new_offset
        new_sels.append(sublime.Region(a, b))
    return new_sels


# The new ST3 plugin API sucks
class FlooViewReplaceRegion(sublime_plugin.TextCommand):
    def run(self, edit, *args, **kwargs):
        selections = [x for x in self.view.sel()]  # deep copy
        selections = self._run(edit, selections, *args, **kwargs)
        self.view.sel().clear()
        for sel in selections:
            self.view.sel().add(sel)

    def _run(self, edit, selections, r, data, view=None):
        global ignore_modified_timeout

        if not hasattr(self, 'view'):
            return selections

        G.IGNORE_MODIFIED_EVENTS = True
        utils.cancel_timeout(ignore_modified_timeout)
        ignore_modified_timeout = utils.set_timeout(unignore_modified_events, 2)
        start = max(int(r[0]), 0)
        stop = min(int(r[1]), self.view.size())
        region = sublime.Region(start, stop)

        if stop - start > 10000:
            self.view.replace(edit, region, data)
            G.VIEW_TO_HASH[self.view.buffer_id()] = hashlib.md5(sutils.get_text(self.view).encode('utf-8')).hexdigest()
            return transform_selections(selections, stop, 0)

        existing = self.view.substr(region)
        i = 0
        data_len = len(data)
        existing_len = len(existing)
        length = min(data_len, existing_len)
        while (i < length):
            if existing[i] != data[i]:
                break
            i += 1
        j = 0
        while j < (length - i):
            if existing[existing_len - j - 1] != data[data_len - j - 1]:
                break
            j += 1
        region = sublime.Region(start + i, stop - j)
        replace_str = data[i:data_len - j]
        self.view.replace(edit, region, replace_str)
        G.VIEW_TO_HASH[self.view.buffer_id()] = hashlib.md5(sutils.get_text(self.view).encode('utf-8')).hexdigest()
        new_offset = len(replace_str) - ((stop - j) - (start + i))
        return transform_selections(selections, start + i, new_offset)

    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    def description(self):
        return


# The new ST3 plugin API sucks
class FlooViewReplaceRegions(FlooViewReplaceRegion):
    def run(self, edit, commands):
        is_read_only = self.view.is_read_only()
        self.view.set_read_only(False)
        selections = [x for x in self.view.sel()]  # deep copy
        for command in commands:
            selections = self._run(edit, selections, **command)

        self.view.set_read_only(is_read_only)
        self.view.sel().clear()
        for sel in selections:
            self.view.sel().add(sel)

    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    def description(self):
        return


called_plugin_loaded = False


# Sublime 3 calls this once the plugin API is ready
def plugin_loaded():
    global called_plugin_loaded
    if called_plugin_loaded:
        return
    called_plugin_loaded = True
    print('Floobits: Called plugin_loaded.')

    utils.reload_settings()

    # TODO: one day this can be removed (once all our users have updated)
    old_colab_dir = os.path.realpath(os.path.expanduser(os.path.join('~', '.floobits')))
    if os.path.isdir(old_colab_dir) and not os.path.exists(G.BASE_DIR):
        print('renaming %s to %s' % (old_colab_dir, G.BASE_DIR))
        os.rename(old_colab_dir, G.BASE_DIR)
        os.symlink(G.BASE_DIR, old_colab_dir)

    try:
        utils.normalize_persistent_data()
    except Exception as e:
        print('Floobits: Error normalizing persistent data:', e)
        # Keep on truckin' I guess

    d = utils.get_persistent_data()
    G.AUTO_GENERATED_ACCOUNT = d.get('auto_generated_account', False)

    can_auth = (G.USERNAME or G.API_KEY) and G.SECRET
    # Sublime plugin API stuff can't be called right off the bat
    if not can_auth:
        utils.set_timeout(create_or_link_account, 1)

    utils.set_timeout(global_tick, 1)

# Sublime 2 has no way to know when plugin API is ready. Horrible hack here.
if PY2:
    for i in range(0, 20):
        threading.Timer(i, utils.set_timeout, [plugin_loaded, 1]).start()

    def warning():
        if not called_plugin_loaded:
            print('Your computer is slow and could not start the Floobits reactor.  Please contact us or upgrade to Sublime Text 3.')
    threading.Timer(20, warning).start()

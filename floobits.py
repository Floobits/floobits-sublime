# coding: utf-8
try:
    unicode()
except NameError:
    unicode = str

import sys
import os
import re
import hashlib
import imp
import json
import uuid
import binascii
import subprocess
import traceback
import webbrowser
import threading
from collections import defaultdict

import sublime_plugin
import sublime

PY2 = sys.version_info < (3, 0)

try:
    import ssl
    assert ssl
except ImportError:
    ssl = False

if ssl is False and sublime.platform() == 'linux':
    plugin_path = os.path.dirname(os.path.realpath(__file__))
    if plugin_path in ('.', ''):
        plugin_path = os.getcwd()
    _ssl = None
    ssl_versions = ['0.9.8', '1.0.0', '10', '1.0.1']
    ssl_path = os.path.join(plugin_path, 'lib', 'linux')
    lib_path = os.path.join(plugin_path, 'lib', 'linux-%s' % sublime.arch())
    if not PY2:
        ssl_path += '-py3'
        lib_path += '-py3'
    for version in ssl_versions:
        so_path = os.path.join(lib_path, 'libssl-%s' % version)
        try:
            filename, path, desc = imp.find_module('_ssl', [so_path])
            if filename is None:
                print('Module not found at %s' % so_path)
                continue
            _ssl = imp.load_module('_ssl', filename, path, desc)
            break
        except ImportError as e:
            print('Failed loading _ssl module %s: %s' % (so_path, unicode(e)))
    if _ssl:
        print('Hooray! %s is a winner!' % so_path)
        filename, path, desc = imp.find_module('ssl', [ssl_path])
        if filename is None:
            print('Couldn\'t find ssl module at %s' % ssl_path)
        else:
            try:
                ssl = imp.load_module('ssl', filename, path, desc)
            except ImportError as e:
                print('Failed loading ssl module at: %s' % unicode(e))
    else:
        print('Couldn\'t find an _ssl shared lib that\'s compatible with your version of linux. Sorry :(')


try:
    from urllib.error import HTTPError
    from .floo import api, AgentConnection, CreateAccountConnection, RequestCredentialsConnection, listener, msg, shared as G, utils
    from .floo.listener import Listener
    assert HTTPError and api and AgentConnection and CreateAccountConnection and RequestCredentialsConnection and G and Listener and listener and msg and utils
except (ImportError, ValueError):
    from urllib2 import HTTPError
    from floo import api, AgentConnection, CreateAccountConnection, RequestCredentialsConnection, listener, msg, utils
    from floo.listener import Listener
    from floo import shared as G


utils.reload_settings()

# TODO: one day this can be removed (once all our users have updated)
old_colab_dir = os.path.realpath(os.path.expanduser(os.path.join('~', '.floobits')))
if os.path.isdir(old_colab_dir) and not os.path.exists(G.BASE_DIR):
    print('renaming %s to %s' % (old_colab_dir, G.BASE_DIR))
    os.rename(old_colab_dir, G.BASE_DIR)
    os.symlink(G.BASE_DIR, old_colab_dir)


on_room_info_waterfall = utils.Waterfall()


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


def add_workspace_to_persistent_json(owner, name, url, path):
    d = utils.get_persistent_data()
    workspaces = d['workspaces']
    if owner not in workspaces:
        workspaces[owner] = {}
    workspaces[owner][name] = {'url': url, 'path': path}
    utils.update_persistent_data(d)


def get_legacy_projects():
    a = ['msgs.floobits.log', 'persistent.json']
    owners = os.listdir(G.COLAB_DIR)
    floorc_json = defaultdict(defaultdict)
    for owner in owners:
        if len(owner) > 0 and owner[0] == '.':
            continue
        if owner in a:
            continue
        workspaces_path = os.path.join(G.COLAB_DIR, owner)
        try:
            workspaces = os.listdir(workspaces_path)
        except OSError:
            continue
        for workspace in workspaces:
            workspace_path = os.path.join(workspaces_path, workspace)
            workspace_path = os.path.realpath(workspace_path)
            try:
                fd = open(os.path.join(workspace_path, '.floo'), 'rb')
                url = json.loads(fd.read())['url']
                fd.close()
            except Exception:
                url = utils.to_workspace_url({
                    'port': 3448, 'secure': True, 'host': 'floobits.com', 'owner': owner, 'workspace': workspace
                })
            floorc_json[owner][workspace] = {
                'path': workspace_path,
                'url': url
            }

    return floorc_json


def migrate_symlinks():
    data = {}
    old_path = os.path.join(G.COLAB_DIR, 'persistent.json')
    if not os.path.exists(old_path):
        return
    old_data = utils.get_persistent_data(old_path)
    data['workspaces'] = get_legacy_projects()
    data['recent_workspaces'] = old_data.get('recent_workspaces')
    utils.update_persistent_data(data)
    try:
        os.unlink(old_path)
        os.unlink(os.path.join(G.COLAB_DIR, 'msgs.floobits.log'))
    except Exception:
        pass
    print('migrated')

migrate_symlinks()

d = utils.get_persistent_data()
G.AUTO_GENERATED_ACCOUNT = d.get('auto_generated_account', False)


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
        agent = RequestCredentialsConnection(token)
    elif not utils.get_persistent_data().get('disable_account_creation'):
        agent = CreateAccountConnection()

    if not agent:
        sublime.error_message('A configuration error occured earlier. Please go to floobits.com and sign up to use this plugin.\n\nWe\'re really sorry. This should never happen.')
        return

    try:
        Listener.reset()
        G.AGENT = agent
        agent.connect()
    except Exception as e:
        print(e)
        tb = traceback.format_exc()
        print(tb)


can_auth = (G.USERNAME or G.API_KEY) and G.SECRET
if not can_auth:
    threading.Timer(0.5, utils.set_timeout, [create_or_link_account, 1]).start()


def global_tick():
    Listener.push()
    if G.AGENT and G.AGENT.sock:
        G.AGENT.select()
    utils.set_timeout(global_tick, G.TICK_TIME)


def disconnect_dialog():
    if G.AGENT and G.JOINED_WORKSPACE:
        disconnect = sublime.ok_cancel_dialog('You can only be in one workspace at a time.', 'Leave workspace %s.' % G.AGENT.workspace)
        if disconnect:
            msg.debug('Stopping agent.')
            G.AGENT.stop()
            G.AGENT = None
        return disconnect
    return True


def on_room_info_msg():
    who = 'Your friends'
    anon_perms = G.AGENT.workspace_info.get('anon_perms')
    if 'get_buf' in anon_perms:
        who = 'Anyone'
    _msg = 'You just joined the workspace: \n\n%s\n\n%s can join this workspace in Floobits or by visiting it in a browser.' % (G.AGENT.workspace_url, who)
    sublime.message_dialog(_msg)


class FloobitsBaseCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return bool(self.is_enabled())

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

    def run(self, dir_to_share='', paths=None, current_file=False):
        utils.reload_settings()
        if not (G.USERNAME and G.SECRET):
            return create_or_link_account()
        if paths:
            if len(paths) != 1:
                return sublime.error_message('Only one folder at a time, please. :(')
            return self.on_input(paths[0])
        self.window.show_input_panel('Directory to share:', dir_to_share, self.on_input, None, None)

    def on_input(self, dir_to_share):
        file_to_share = None
        dir_to_share = os.path.expanduser(dir_to_share)
        dir_to_share = os.path.realpath(utils.unfuck_path(dir_to_share))
        workspace_name = os.path.basename(dir_to_share)
        floo_workspace_dir = os.path.join(G.COLAB_DIR, G.USERNAME, workspace_name)
        print(G.COLAB_DIR, G.USERNAME, workspace_name, floo_workspace_dir)

        if os.path.isfile(dir_to_share):
            file_to_share = dir_to_share
            dir_to_share = os.path.dirname(dir_to_share)
        else:
            try:
                utils.mkdir(dir_to_share)
            except Exception:
                return sublime.error_message('The directory %s doesn\'t exist and I can\'t make it.' % dir_to_share)

            floo_file = os.path.join(dir_to_share, '.floo')

            info = {}
            try:
                floo_info = open(floo_file, 'rb').read().decode('utf-8')
                info = json.loads(floo_info)
            except (IOError, OSError):
                pass
            except Exception:
                print('Couldn\'t read the floo_info file: %s' % floo_file)

            workspace_url = info.get('url')
            try:
                result = utils.parse_url(workspace_url)
            except Exception:
                workspace_url = None
            else:
                workspace_name = result['workspace']
                try:
                    # TODO: blocking. beachballs sublime 2 if API is super slow
                    api.get_workspace_by_url(workspace_url)
                except HTTPError:
                    workspace_url = None
                    workspace_name = os.path.basename(dir_to_share)
                else:
                    add_workspace_to_persistent_json(result['owner'], result['workspace'], workspace_url, dir_to_share)

        for owner, workspaces in utils.get_persistent_data()['workspaces'].items():
            for name, workspace in workspaces.items():
                if workspace['path'] == dir_to_share:
                    workspace_url = workspace['url']
                    print('found workspace url', workspace_url)
                    break

        if workspace_url:
            try:
                api.get_workspace_by_url(workspace_url)
            except HTTPError:
                pass
            else:
                on_room_info_waterfall.add(on_room_info_msg)
                on_room_info_waterfall.add(Listener.create_buf, dir_to_share)
                return self.window.run_command('floobits_join_workspace', {'workspace_url': workspace_url})

        # make & join workspace
        on_room_info_waterfall.add(Listener.create_buf, file_to_share or dir_to_share)
        self.window.run_command('floobits_create_workspace', {
            'workspace_name': workspace_name,
            'dir_to_share': dir_to_share,
        })


class FloobitsCreateWorkspaceCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    def run(self, workspace_name=None, dir_to_share=None, prompt='Workspace name:'):
        if not disconnect_dialog():
            return
        if ssl is False:
            return sublime.error_message('Your version of Sublime Text can\'t create workspaces because it has a broken SSL module. '
                                         'This is a known issue on Linux and Windows builds of Sublime Text 2. '
                                         'Please upgrade to Sublime Text 3. See http://sublimetext.userecho.com/topic/50801-bundle-python-ssl-module/ for more information.')
        self.owner = G.USERNAME
        self.dir_to_share = dir_to_share
        self.workspace_name = workspace_name
        if workspace_name and dir_to_share and prompt == 'Workspace name:':
            return self.on_input(workspace_name, dir_to_share)
        self.window.show_input_panel(prompt, workspace_name, self.on_input, None, None)

    def on_input(self, workspace_name, dir_to_share=None):
        if dir_to_share:
            self.dir_to_share = dir_to_share
        if workspace_name == '':
            return self.run(dir_to_share=self.dir_to_share)
        try:
            api.create_workspace(workspace_name)
            workspace_url = 'https://%s/r/%s/%s' % (G.DEFAULT_HOST, G.USERNAME, workspace_name)
            print('Created workspace %s' % workspace_url)
        except HTTPError as e:
            if e.code not in [400, 409]:
                return sublime.error_message('Unable to create workspace: %s' % unicode(e))
            kwargs = {
                'dir_to_share': self.dir_to_share,
                'workspace_name': workspace_name,
            }
            if e.code == 400:
                kwargs['workspace_name'] = re.sub('[^A-Za-z0-9_\-]', '-', workspace_name)
                kwargs['prompt'] = 'Invalid name. Workspace names must match the regex [A-Za-z0-9_\-]. Choose another name:'
            else:
                kwargs['prompt'] = 'Workspace %s already exists. Choose another name:' % workspace_name

            return self.window.run_command('floobits_create_workspace', kwargs)

        except Exception as e:
            return sublime.error_message('Unable to create workspace: %s' % unicode(e))

        add_workspace_to_persistent_json(G.USERNAME, workspace_name, workspace_url, self.dir_to_share)

        on_room_info_waterfall.add(on_room_info_msg)

        self.window.run_command('floobits_join_workspace', {
            'workspace_url': workspace_url,
        })


class FloobitsPromptJoinWorkspaceCommand(sublime_plugin.WindowCommand):

    def run(self, workspace='https://floobits.com/r/'):
        self.window.show_input_panel('Workspace URL:', workspace, self.on_input, None, None)

    def on_input(self, workspace_url):
        if disconnect_dialog():
            self.window.run_command('floobits_join_workspace', {
                'workspace_url': workspace_url,
            })


class FloobitsJoinWorkspaceCommand(sublime_plugin.WindowCommand):

    def run(self, workspace_url):

        def truncate_chat_view(chat_view, cb):
            if chat_view:
                chat_view.set_read_only(False)
                chat_view.run_command('floo_view_replace_region', {'r': [0, chat_view.size()], 'data': ''})
                chat_view.set_read_only(True)
            cb()

        def create_chat_view(cb):
            with open(os.path.join(G.BASE_DIR, 'msgs.floobits.log'), 'a') as msgs_fd:
                msgs_fd.write('')
            msg.get_or_create_chat(lambda chat_view: truncate_chat_view(chat_view, cb))

        def open_workspace_window2(cb):
            if sublime.platform() == 'linux':
                subl = open('/proc/self/cmdline').read().split(chr(0))[0]
            elif sublime.platform() == 'osx':
                # TODO: totally explodes if you install ST2 somewhere else
                settings = sublime.load_settings('Floobits.sublime-settings')
                subl = settings.get('sublime_executable', '/Applications/Sublime Text 2.app/Contents/SharedSupport/bin/subl')
                if not os.path.exists(subl):
                    return sublime.error_message('Can\'t find your Sublime Text executable at %s. Please add "sublime_executable /path/to/subl" to your ~/.floorc and restart Sublime Text' % subl)
            elif sublime.platform() == 'windows':
                subl = sys.executable
            else:
                raise Exception('WHAT PLATFORM ARE WE ON?!?!?')

            command = [subl]
            if utils.get_workspace_window() is None:
                command.append('--new-window')
            command.append('--add')
            command.append(G.PROJECT_PATH)

            # Maybe no msg view yet :(
            print('command:', command)
            p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            poll_result = p.poll()
            print('poll:', poll_result)

            utils.set_workspace_window(lambda: create_chat_view(cb))

        def open_workspace_window3(cb):
            G.WORKSPACE_WINDOW = utils.get_workspace_window()
            if not G.WORKSPACE_WINDOW:
                G.WORKSPACE_WINDOW = sublime.active_window()
            msg.debug('Setting project data. Path: %s' % G.PROJECT_PATH)
            G.WORKSPACE_WINDOW.set_project_data({'folders': [{'path': G.PROJECT_PATH}]})
            create_chat_view(cb)

        def open_workspace_window(cb):
            if PY2:
                open_workspace_window2(cb)
            else:
                open_workspace_window3(cb)

        def run_agent(owner, workspace, host, port, secure):
            if G.AGENT:
                msg.debug('Stopping agent.')
                G.AGENT.stop()
                G.AGENT = None

            on_room_info_waterfall.add(update_recent_workspaces, {'url': workspace_url})

            try:
                G.AGENT = AgentConnection(owner=owner, workspace=workspace, host=host, port=port, secure=secure, on_room_info=on_room_info_waterfall.call)
                Listener.reset()
                G.AGENT.connect()
            except Exception as e:
                print(e)
                tb = traceback.format_exc()
                print(tb)

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
            add_workspace_to_persistent_json(result['owner'], result['workspace'], workspace_url, d)
            open_workspace_window(lambda: run_agent(**result))

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
            default_dir = os.path.realpath(os.path.join(G.COLAB_DIR, result['owner'], result['workspace']))
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
        webbrowser.open('https://%s/u/%s/pinocchio/%s/' % (G.DEFAULT_HOST, username, secret))


class FloobitsLeaveWorkspaceCommand(FloobitsBaseCommand):

    def run(self):
        if G.AGENT:
            G.AGENT.stop()
            G.AGENT = None
            # TODO: Mention the name of the thing we left
            sublime.error_message('You have left the workspace.')
        else:
            sublime.error_message('You are not joined to any workspace.')


class FloobitsPromptMsgCommand(FloobitsBaseCommand):

    def run(self, msg=''):
        print(('msg', msg))
        self.window.show_input_panel('msg:', msg, self.on_input, None, None)

    def on_input(self, msg):
        self.window.run_command('floobits_msg', {'msg': msg})


class FloobitsMsgCommand(FloobitsBaseCommand):
    def run(self, msg):
        if not msg:
            return
        if G.AGENT:
            G.AGENT.send_msg(msg)

    def description(self):
        return 'Send a message to the floobits workspace you are in (join a workspace first)'


class FloobitsClearHighlightsCommand(FloobitsBaseCommand):
    def run(self):
        Listener.clear_highlights(self.window.active_view())


class FloobitsSummonCommand(FloobitsBaseCommand):
    # TODO: ghost this option if user doesn't have permissions
    def run(self):
        Listener.summon(self.window.active_view())


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


class FloobitsOpenMessageViewCommand(FloobitsBaseCommand):
    def run(self, *args):
        def print_msg(chat_view):
            msg.log('Opened message view')
            if not G.AGENT:
                msg.log('Not joined to a workspace.')

        msg.get_or_create_chat(print_msg)

    def description(self):
        return 'Open the floobits messages view.'


class FloobitsAddToWorkspaceCommand(FloobitsBaseCommand):
    def run(self, paths, current_file=False):
        if not self.is_enabled():
            return

        if paths is None and current_file:
            paths = [self.window.active_view().file_name()]

        for path in paths:
            Listener.create_buf(path)

    def description(self):
        return 'Add file or directory to currently-joined Floobits workspace.'


class FloobitsDeleteFromWorkspaceCommand(FloobitsBaseCommand):
    def run(self, paths, current_file=False):
        if not self.is_enabled():
            return

        confirm = bool(sublime.ok_cancel_dialog('This will delete your local copy as well. Are you sure you want do do this?', 'Delete'))
        if not confirm:
            return

        if paths is None and current_file:
            paths = [self.window.active_view().file_name()]

        for path in paths:
            Listener.delete_buf(path)

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
                'port': agent.port,
                'secure': agent.secure,
                'owner': agent.owner,
                'workspace': agent.workspace,
                'host': agent.host,
            })
            webbrowser.open(url)
        except Exception as e:
            sublime.error_message('Unable to open workspace in web editor: %s' % unicode(e))


class FloobitsHelpCommand(FloobitsBaseCommand):
    def run(self):
        webbrowser.open('https://floobits.com/help/plugins/#sublime-usage', new=2, autoraise=True)

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


class FloobitsEnableStalkerModeCommand(FloobitsBaseCommand):
    def run(self):
        G.STALKER_MODE = True
        # TODO: go to most recent highlight

    def is_enabled(self):
        return bool(super(FloobitsEnableStalkerModeCommand, self).is_enabled() and not G.STALKER_MODE)


class FloobitsDisableStalkerModeCommand(FloobitsBaseCommand):
    def run(self):
        G.STALKER_MODE = False

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
        G.AGENT.put({
            'name': 'request_perms',
            'perms': perms
        })

    def is_enabled(self):
        if not super(RequestPermissionCommand, self).is_enabled():
            return False
        if 'patch' in G.PERMS:
            return False
        return True


class FloobitsNotACommand(sublime_plugin.WindowCommand):
    def run(self, *args, **kwargs):
        pass

    def is_visible(self):
        return True

    def is_enabled(self):
        return False

    def description(self):
        return


# The new ST3 plugin API sucks
class FlooViewSetMsg(sublime_plugin.TextCommand):
    def run(self, edit, data, *args, **kwargs):
        size = self.view.size()
        self.view.set_read_only(False)
        self.view.insert(edit, size, data)
        self.view.set_read_only(True)
        # TODO: this scrolling is lame and centers text :/
        self.view.show(size)

    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    def description(self):
        return


ignore_modified_timeout = None


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

        if not getattr(self, 'view', None):
            return selections

        G.IGNORE_MODIFIED_EVENTS = True
        utils.cancel_timeout(ignore_modified_timeout)
        ignore_modified_timeout = utils.set_timeout(unignore_modified_events, 2)
        start = max(int(r[0]), 0)
        stop = min(int(r[1]), self.view.size())
        region = sublime.Region(start, stop)

        if stop - start > 10000:
            self.view.replace(edit, region, data)
            G.VIEW_TO_HASH[self.view.buffer_id()] = hashlib.md5(listener.get_text(self.view).encode('utf-8')).hexdigest()
            return transform_selections(selections, start, stop - start)

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
        G.VIEW_TO_HASH[self.view.buffer_id()] = hashlib.md5(listener.get_text(self.view).encode('utf-8')).hexdigest()
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


global_tick()

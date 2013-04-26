# coding: utf-8
import os
import sys
import json
import threading
import traceback
import subprocess
import urllib2
import webbrowser

import sublime_plugin
import sublime

from floo import api
from floo import AgentConnection
from floo.listener import Listener
from floo import msg
from floo import shared as G
from floo import utils

settings = sublime.load_settings('Floobits.sublime-settings')

DATA = utils.get_persistent_data()
agent = None
ON_CONNECT = None


def update_recent_rooms(room):
    recent_rooms = DATA.get('recent_rooms', [])
    recent_rooms.insert(0, room)
    recent_rooms = recent_rooms[:25]
    seen = set()
    new = []
    for r in recent_rooms:
        stringified = json.dumps(r)
        if stringified not in seen:
            new.append(r)
            seen.add(stringified)

    DATA['recent_rooms'] = new
    utils.update_persistent_data(DATA)


def load_floorc():
    """try to read settings out of the .floorc file"""
    s = {}
    try:
        fd = open(os.path.expanduser('~/.floorc'), 'rb')
    except IOError as e:
        if e.errno == 2:
            return s
        raise

    default_settings = fd.read().split('\n')
    fd.close()

    for setting in default_settings:
        # TODO: this is horrible
        if len(setting) == 0 or setting[0] == '#':
            continue
        try:
            name, value = setting.split(' ', 1)
        except IndexError:
            continue
        s[name.upper()] = value
    return s


def reload_settings():
    global settings
    print('Reloading settings...')
    settings = sublime.load_settings('Floobits.sublime-settings')
    G.ALERT_ON_MSG = settings.get('alert_on_msg', True)
    G.DEBUG = settings.get('debug', False)
    G.COLAB_DIR = settings.get('share_dir', '~/.floobits/share/')
    G.COLAB_DIR = os.path.expanduser(G.COLAB_DIR)
    G.COLAB_DIR = os.path.realpath(G.COLAB_DIR)
    utils.mkdir(G.COLAB_DIR)
    G.DEFAULT_HOST = settings.get('host', 'floobits.com')
    G.DEFAULT_PORT = settings.get('port', 3448)
    G.SECURE = settings.get('secure', True)
    G.USERNAME = settings.get('username')
    G.SECRET = settings.get('secret')
    floorc_settings = load_floorc()
    for name, val in floorc_settings.items():
        setattr(G, name, val)
    if agent and agent.is_ready():
        msg.log('Reconnecting due to settings change')
        agent.reconnect()

settings.add_on_change('', reload_settings)
reload_settings()


class FloobitsBaseCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return agent and agent.is_ready()


class FloobitsShareDirCommand(sublime_plugin.WindowCommand):

    def run(self, dir_to_share=''):
        self.window.show_input_panel('Directory:', dir_to_share, self.on_input, None, None)

    def on_input(self, dir_to_share):
        global ON_CONNECT
        dir_to_share = os.path.expanduser(dir_to_share)
        dir_to_share = utils.unfuck_path(dir_to_share)
        room_name = os.path.basename(dir_to_share)
        floo_room_dir = os.path.join(G.COLAB_DIR, G.USERNAME, room_name)
        print(G.COLAB_DIR, G.USERNAME, room_name, floo_room_dir)

        if os.path.isfile(dir_to_share):
            return sublime.error_message('give me a directory please')

        if not os.path.isdir(dir_to_share):
            return sublime.error_message('The directory %s doesn\'t appear to exist' % dir_to_share)

        floo_file = os.path.join(dir_to_share, '.floo')

        info = {}
        try:
            floo_info = open(floo_file, 'rb').read().decode('utf-8')
            info = json.loads(floo_info)
        except (IOError, OSError):
            pass
        except Exception:
            print("couldn't read the floo_info file: %s" % floo_file)

        room_url = info.get('url')
        if room_url:
            try:
                result = utils.parse_url(room_url)
            except Exception as e:
                sublime.error_message(str(e))
            else:
                room_name = result['room']
                floo_room_dir = os.path.join(G.COLAB_DIR, result['owner'], result['room'])
                if os.path.realpath(floo_room_dir) == os.path.realpath(dir_to_share):
                    if result['owner'] == G.USERNAME:
                        try:
                            api.create_room(room_name)
                            print('Created room %s' % room_url)
                        except Exception as e:
                            print('Tried to create room' + str(e))
                    # they wanted to share teh dir, so always share it
                    return self.window.run_command('floobits_join_room', {'room_url': room_url})
        # go make sym link
        try:
            utils.mkdir(os.path.dirname(floo_room_dir))
            os.symlink(dir_to_share, floo_room_dir)
        except OSError as e:
            if e.errno != 17:
                raise
        except Exception as e:
            return sublime.error_message("Couldn't create symlink from %s to %s: %s" % (dir_to_share, floo_room_dir, str(e)))

        # make & join room
        ON_CONNECT = lambda x: Listener.create_buf(dir_to_share)
        self.window.run_command('floobits_create_room', {
            'room_name': room_name,
            'ln_path': floo_room_dir,
        })

    def is_enabled(self):
        return not bool(agent and agent.is_ready())


class FloobitsCreateRoomCommand(sublime_plugin.WindowCommand):

    def run(self, room_name='', ln_path=None, prompt='Room name:'):
        self.ln_path = ln_path
        self.window.show_input_panel(prompt, room_name, self.on_input, None, None)

    def on_input(self, room_name):
        try:
            api.create_room(room_name)
            room_url = 'https://%s/r/%s/%s' % (G.DEFAULT_HOST, G.USERNAME, room_name)
            print('Created room %s' % room_url)
        except urllib2.HTTPError, e:
            if e.code != 409:
                raise
            args = {
                'room_name': room_name,
                'prompt': 'Room %s already exists. Choose another name:' % room_name
            }

            if self.ln_path:
                while True:
                    room_name = room_name + '1'
                    new_path = os.path.join(os.path.dirname(self.ln_path), room_name)
                    try:
                        os.rename(self.ln_path, new_path)
                    except OSError:
                        continue
                    args = {
                        'ln_path': new_path,
                        'room_name': room_name,
                        'prompt': 'Room %s already exists. Choose another name:' % room_name
                    }
                    break

            return self.window.run_command('floobits_create_room', args)
        except urllib2.URLError, e:
            sublime.error_message('Unable to create room: %s' % str(e))
            return

        webbrowser.open(room_url + '/settings', new=2, autoraise=True)

        self.window.run_command('floobits_join_room', {
            'room_url': room_url,
        })

    def is_enabled(self):
        return not bool(agent and agent.is_ready())


class FloobitsPromptJoinRoomCommand(sublime_plugin.WindowCommand):

    def run(self, room=''):
        self.window.show_input_panel('Room URL:', room, self.on_input, None, None)

    def on_input(self, room_url):
        self.window.run_command('floobits_join_room', {
            'room_url': room_url,
        })

    def is_enabled(self):
        return not bool(agent and agent.is_ready())


class FloobitsJoinRoomCommand(sublime_plugin.WindowCommand):

    def run(self, room_url):
        def open_room_window(cb):
            if sublime.platform() == 'linux':
                subl = open('/proc/self/cmdline').read().split(chr(0))[0]
            elif sublime.platform() == 'osx':
                # TODO: totally explodes if you install ST2 somewhere else
                subl = settings.get('sublime_executable', '/Applications/Sublime Text 2.app/Contents/SharedSupport/bin/subl')
            elif sublime.platform() == 'windows':
                subl = sys.executable
            else:
                raise Exception('WHAT PLATFORM ARE WE ON?!?!?')

            command = [subl]
            if utils.get_room_window() is None:
                command.append('--new-window')
            command.append('--add')
            command.append(G.PROJECT_PATH)
            print('command:', command)
            p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            poll_result = p.poll()
            print('poll:', poll_result)

            def create_chat_view():
                with open(os.path.join(G.COLAB_DIR, 'msgs.floobits.log'), 'w') as msgs_fd:
                    msgs_fd.write('')
                msg.get_or_create_chat(cb)
            utils.set_room_window(create_chat_view)

        def run_agent(owner, room, host, port, secure):
            global agent
            if agent:
                agent.stop()
                agent = None
            try:
                agent = AgentConnection(owner, room, host=host, port=port, secure=secure, on_connect=ON_CONNECT)
                # owner and room name are slugfields so this should be safe
                Listener.set_agent(agent)
                agent.connect()
            except Exception as e:
                print(e)
                tb = traceback.format_exc()
                print(tb)
            else:
                joined_room = {'url': room_url}
                update_recent_rooms(joined_room)

        try:
            result = utils.parse_url(room_url)
        except Exception as e:
            return sublime.error_message(str(e))

        def run_thread(*args):
            thread = threading.Thread(target=run_agent, kwargs=result)
            thread.start()

        def link_dir(d):
            if d == '':
                utils.mkdir(G.PROJECT_PATH)
            else:
                try:
                    utils.mkdir(os.path.dirname(G.PROJECT_PATH))
                    d = os.path.realpath(os.path.expanduser(d))
                    if not os.path.isdir(d):
                        return self.window.show_input_panel('%s is not a directory. Enter an existing path:' % d, d, link_dir, None, None)
                    os.symlink(d, G.PROJECT_PATH)
                except Exception as e:
                    return sublime.error_message("Couldn't create symlink from %s to %s: %s" % (d, G.PROJECT_PATH, str(e)))

            open_room_window(run_thread)

        G.PROJECT_PATH = os.path.realpath(os.path.join(G.COLAB_DIR, result['owner'], result['room']))
        if not os.path.isdir(G.PROJECT_PATH):
            # TODO: really bad prompt here
            return self.window.show_input_panel('Give me a directory to destructively dump data into (or just press enter):', '', link_dir, None, None)

        open_room_window(run_thread)


class FloobitsLeaveRoomCommand(FloobitsBaseCommand):

    def run(self):
        global agent
        if agent:
            agent.stop()
            agent = None
            sublime.error_message('You have left the room.')
        else:
            sublime.error_message('You are not joined to any room.')


class FloobitsPromptMsgCommand(FloobitsBaseCommand):

    def run(self, msg=''):
        print('msg', msg)
        self.window.show_input_panel('msg:', msg, self.on_input, None, None)

    def on_input(self, msg):
        self.window.run_command('floobits_msg', {'msg': msg})


class FloobitsMsgCommand(FloobitsBaseCommand):
    def run(self, msg):
        if not msg:
            return
        if agent:
            agent.send_msg(msg)

    def description(self):
        return 'Send a message to the floobits room you are in (join a room first)'


class FloobitsPingCommand(FloobitsBaseCommand):
    # TODO: ghost this option if user doesn't have permissions
    def run(self):
        Listener.ping(self.window.active_view())


class FloobitsJoinRecentRoomCommand(sublime_plugin.WindowCommand):
    def run(self, *args):
        rooms = [x.get('url') for x in DATA['recent_rooms'] if x.get('url') is not None]
        self.window.show_quick_panel(rooms, self.on_done)

    def on_done(self, item):
        if item == -1:
            return
        room = DATA['recent_rooms'][item]
        self.window.run_command('floobits_join_room', {'room_url': room['url']})


class FloobitsOpenMessageViewCommand(FloobitsBaseCommand):
    def run(self, *args):
        def print_msg(chat_view):
            msg.log('Opened message view')
            if not agent:
                msg.log('Not joined to a room.')

        msg.get_or_create_chat(print_msg)

    def description(self):
        return 'Open the floobits messages view.'


class FloobitsAddToRoomCommand(FloobitsBaseCommand):
    def run(self, paths):
        if not self.is_enabled():
            return
        for path in paths:
            Listener.create_buf(path)

    def description(self):
        return 'Add file or directory to currently-joined Floobits room.'


class FloobitsDeleteFromRoomCommand(FloobitsBaseCommand):
    def run(self, paths):
        if not self.is_enabled():
            return
        for path in paths:
            Listener.delete_buf(path)

    def description(self):
        return 'Add file or directory to currently-joined Floobits room.'


class FloobitsEnableFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        G.FOLLOW_MODE = True
        # TODO: go to most recent highlight

    def is_visible(self):
        return bool(self.is_enabled())

    def is_enabled(self):
        return bool(agent and agent.is_ready() and not G.FOLLOW_MODE)


class FloobitsDisableFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        G.FOLLOW_MODE = False

    def is_visible(self):
        return bool(self.is_enabled())

    def is_enabled(self):
        return bool(agent and agent.is_ready() and G.FOLLOW_MODE)


class FloobitsNotACommand(sublime_plugin.WindowCommand):
    def run(self, *args, **kwargs):
        pass

    def is_visible(self):
        return True

    def is_enabled(self):
        return False

    def description(self):
        return

Listener.push()

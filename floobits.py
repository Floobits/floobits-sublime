# coding: utf-8
import re
import os
import json
import threading
import traceback
import urllib.error
from urllib.parse import urlparse

import sublime_plugin
import sublime

from .floo import api
from .floo import AgentConnection
from .floo.listener import Listener
from .floo import msg
from .floo import shared as G
from .floo import utils

settings = sublime.load_settings('Floobits.sublime-settings')

G.PLUGIN_PATH = os.path.split(__file__)[0]
DATA = utils.get_persistent_data()
agent = None


def update_recent_rooms(room):
    recent_rooms = DATA.get('recent_rooms', [])
    recent_rooms.insert(0, room)
    recent_rooms = recent_rooms[:25]
    seen = set()
    new = []
    print(room)
    for r in recent_rooms:
        stringified = json.dumps(r)
        if stringified not in seen:
            new.append(r)
            seen.add(stringified)

    DATA['recent_rooms'] = new
    utils.update_persistent_data(DATA)


def reload_settings():
    print('Reloading settings...')
    settings = sublime.load_settings('Floobits.sublime-settings')
    G.ALERT_ON_MSG = settings.get('alert_on_msg', True)
    G.DEBUG = settings.get('debug', False)
    G.COLAB_DIR = settings.get('share_dir') or '~/.floobits/share/'
    G.COLAB_DIR = os.path.expanduser(G.COLAB_DIR)
    G.COLAB_DIR = os.path.realpath(G.COLAB_DIR)
    utils.mkdir(G.COLAB_DIR)
    G.DEFAULT_HOST = settings.get('host') or 'floobits.com'
    G.DEFAULT_PORT = settings.get('port') or 3448
    G.SECURE = settings.get('secure')
    if G.SECURE is None:
        G.SECURE = True
    G.USERNAME = settings.get('username')
    G.SECRET = settings.get('secret')
    if agent and agent.is_ready():
        msg.log('Reconnecting due to settings change')
        agent.reconnect()

settings.add_on_change('', reload_settings)
reload_settings()


class FloobitsBaseCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return bool(self.is_enabled())

    def is_enabled(self):
        return bool(agent and agent.is_ready())


class FloobitsCreateRoomCommand(sublime_plugin.WindowCommand):

    def run(self, room=''):
        self.window.show_input_panel('Room name:', room, self.on_input, None, None)

    def on_input(self, room):
        try:
            api.create_room(room)
            room_url = 'https://%s/r/%s/%s' % (G.DEFAULT_HOST, G.USERNAME, room)
            msg.log('Created room %s' % room_url)
        except urllib.error.URLError as e:
            sublime.error_message('Unable to create room: %s' % str(e))
            return

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
            G.ROOM_WINDOW = utils.get_room_window()
            if not G.ROOM_WINDOW:
                G.ROOM_WINDOW = sublime.active_window()
            msg.debug('Setting project data. Path: %s' % G.PROJECT_PATH)
            G.ROOM_WINDOW.set_project_data({'folders': [{'path': G.PROJECT_PATH}]})
            with open(os.path.join(G.COLAB_DIR, 'msgs.floobits.log'), 'w') as msgs_fd:
                msgs_fd.write('')
            msg.get_or_create_chat(cb)

        def run_agent(owner, room, host, port, secure):
            global agent
            if agent:
                msg.debug('Stopping agent.')
                agent.stop()
                agent = None
            try:
                agent = AgentConnection(owner, room, host=host, port=port, secure=secure, on_connect=None)
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

        global agent
        if agent:
            msg.debug('Stopping agent.')
            agent.stop()
            agent = None
        reload_settings()
        secure = G.SECURE
        parsed_url = urlparse(room_url)
        port = parsed_url.port
        if parsed_url.scheme == 'http':
            if not port:
                port = 3148
            secure = False
        result = re.match('^/r/([-\w]+)/([-\w]+)/?$', parsed_url.path)
        if result:
            (owner, room) = result.groups()

            def run_thread(*args):
                thread = threading.Thread(target=run_agent, kwargs={
                    'owner': owner,
                    'room': room,
                    'host': parsed_url.hostname,
                    'port': port,
                    'secure': secure,
                })
                thread.start()

            G.PROJECT_PATH = os.path.realpath(os.path.join(G.COLAB_DIR, owner, room))
            utils.mkdir(G.PROJECT_PATH)
            open_room_window(run_thread)
        else:
            sublime.error_message('Unable to parse your URL!')


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
        print(('msg', msg))
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


# The new ST3 plugin API sucks
class FlooViewReplaceRegion(sublime_plugin.TextCommand):
    def run(self, edit, r, data, *args, **kwargs):
        region = sublime.Region(r[0], r[1])
        self.view.replace(edit, region, data)

    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    def description(self):
        return


Listener.push()

# coding: utf-8
import re
import os
import sys
import json
import threading
import traceback
import subprocess
import urllib2
from urlparse import urlparse

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


def set_active_window():
    w = sublime.active_window()
    if not w:
        return sublime.set_timeout(set_active_window, 100)
    G.ROOM_WINDOW = w

sublime.set_timeout(set_active_window, 0)


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

settings.add_on_change('', reload_settings)
reload_settings()


class FloobitsCreateRoomCommand(sublime_plugin.WindowCommand):

    def run(self, room=''):
        self.window.show_input_panel('Room name:', room, self.on_input, None, None)

    def on_input(self, room):
        try:
            api.create_room(room)
            room_url = 'https://%s/r/%s/%s' % (G.DEFAULT_HOST, G.USERNAME, room)
            msg.log('Created room %s' % room_url)
        except urllib2.URLError as e:
            sublime.error_message('Unable to create room: %s' % str(e))
            return

        self.window.run_command('floobits_join_room', {
            'room_url': room_url,
        })


class FloobitsPromptJoinRoomCommand(sublime_plugin.WindowCommand):

    def run(self, room=''):
        self.window.show_input_panel('Room URL:', room, self.on_input, None, None)

    def on_input(self, room_url):
        self.window.run_command('floobits_join_room', {
            'room_url': room_url,
        })


class FloobitsJoinRoomCommand(sublime_plugin.WindowCommand):

    def run(self, room_url):
        def on_connect(agent_connection):
            if sublime.platform() == 'linux':
                subl = open('/proc/self/cmdline').read().split(chr(0))[0]
            elif sublime.platform() == 'osx':
                # TODO: totally explodes if you install ST2 somewhere else
                subl = '/Applications/Sublime Text 2.app/Contents/SharedSupport/bin/subl'
            elif sublime.platform() == 'windows':
                subl = sys.executable
            else:
                raise Exception('WHAT PLATFORM ARE WE ON?!?!?')

            command = [subl, '--add', G.PROJECT_PATH]
            print('command:', command)
            p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            poll_result = p.poll()
            print('poll:', poll_result)

        def run_agent(owner, room, host, port, secure):
            global agent
            try:
                G.PROJECT_PATH = os.path.realpath(os.path.join(G.COLAB_DIR, owner, room))
                sublime.set_timeout(msg.get_or_create_chat, 0)
                agent = AgentConnection(owner, room, host=host, port=port, secure=secure, on_connect=on_connect)
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
            thread = threading.Thread(target=run_agent, kwargs={
                'owner': owner,
                'room': room,
                'host': parsed_url.hostname,
                'port': port,
                'secure': secure,
            })
            thread.start()
        else:
            sublime.error_message('Unable to parse your URL!')



class FloobitsLeaveRoomCommand(sublime_plugin.WindowCommand):

    def run(self):
        if agent:
            agent.stop()
            sublime.error_message('You have left the room.')
        else:
            sublime.error_message('You are not joined to any room.')


class FloobitsPromptMsgCommand(sublime_plugin.WindowCommand):

    def run(self, msg=''):
        print('msg', msg)
        self.window.show_input_panel('msg:', msg, self.on_input, None, None)

    def on_input(self, msg):
        self.window.active_view().run_command('floobits_msg', {'msg': msg})


class FloobitsMsgCommand(sublime_plugin.TextCommand):
    def run(self, edit, msg):
        if not msg:
            return

        if agent:
            agent.send_msg(msg)

    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return agent and agent.is_ready()

    def description(self):
        return 'Send a message to the floobits room you are in (join a room first)'


class FloobitsJoinRecentRoomCommand(sublime_plugin.WindowCommand):
    def run(self, *args):
        rooms = [x.get('url') for x in DATA['recent_rooms'] if x.get('url') != None]
        print(rooms)
        self.window.show_quick_panel(rooms, self.on_done)

    def on_done(self, item):
        if item == -1:
            return
        room = DATA['recent_rooms'][item]
        self.window.run_command('floobits_join_room', {'room_url': room['url']})


class FloobitsOpenMessageViewCommand(sublime_plugin.WindowCommand):
    def run(self, *args):
        if not agent:
            return
        msg.get_or_create_chat()

    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return agent and agent.is_ready()

    def description(self):
        return 'Open the floobits messages view.'

Listener.push()
agent = None

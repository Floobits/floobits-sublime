
import json
import socket
import Queue
import time
import os
import sublime
import select

import shared as G
import utils
from listener import Listener

settings = sublime.load_settings('Floobits.sublime-settings')

CHAT_VIEW = None
SOCKET_Q = Queue.Queue()


def get_or_create_chat():
    global CHAT_VIEW
    p = utils.get_full_path('floobits.log')
    if not CHAT_VIEW:
        window = sublime.active_window()
        CHAT_VIEW = window.open_file(p)
        CHAT_VIEW.set_read_only(True)
    return CHAT_VIEW


class AgentConnection(object):
    ''' Simple chat server using select '''

    def __init__(self, owner, room, host=None, port=None, on_connect=None):
        self.sock = None
        self.buf = ''
        self.reconnect_delay = 500
        self.username = G.USERNAME
        self.secret = G.SECRET
        self.authed = False
        self.host = host or G.DEFAULT_HOST
        self.port = port or G.DEFAULT_PORT
        self.owner = owner
        self.room = room
        self.retries = G.MAX_RETRIES
        self.on_connect = on_connect

    def stop(self):
        self.sock.shutdown(2)
        self.sock.close()

    def send_msg(self, msg):
        self.put(json.dumps({'name': 'msg', 'data': msg}))
        self.chat(self.username, time.time(), msg)

    def is_ready(self):
        return self.authed

    @staticmethod
    def put(item):
        #TODO: move json_dumps here
        if not item:
            return
        SOCKET_Q.put(item + '\n')
        qsize = SOCKET_Q.qsize()
        if qsize > 0:
            print('%s items in q' % qsize)

    def reconnect(self):
        self.sock = None
        self.authed = False
        self.reconnect_delay *= 1.5
        if self.reconnect_delay > 10000:
            self.reconnect_delay = 10000
        if self.retries > 0:
            print('reconnecting in', self.reconnect_delay)
            sublime.set_timeout(self.connect, int(self.reconnect_delay))
        else:
            print('too many reconnect failures. giving up')

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print('Connecting to %s:%s' % (self.host, self.port))
        try:
            self.sock.connect((self.host, self.port))
        except socket.error as e:
            print('Error connecting:', e)
            self.reconnect()
            return
        self.sock.setblocking(0)
        print('connected, calling select')
        self.reconnect_delay = 1
        sublime.set_timeout(self.select, 0)
        self.auth()

    def auth(self):
        global SOCKET_Q
        # TODO: we shouldn't throw away all of this
        SOCKET_Q = Queue.Queue()
        self.put(json.dumps({
            'username': self.username,
            'secret': self.secret,
            'room': self.room,
            'room_owner': self.owner,
            'version': G.__VERSION__
        }))

    def get_patches(self):
        while True:
            try:
                yield SOCKET_Q.get_nowait()
            except Queue.Empty:
                break

    def chat(self, username, timestamp, msg):
        view = get_or_create_chat()
        envelope = "[{time}] <{user}> {msg}\n".format(user=username, time=time.ctime(timestamp), msg=msg)
        with utils.edit(view) as ed:
            view.set_read_only(False)
            view.insert(ed, view.size(), envelope)
            view.set_read_only(True)

    def protocol(self, req):
        self.buf += req
        while True:
            before, sep, after = self.buf.partition('\n')
            if not sep:
                break
            data = json.loads(before)
            print(data)
            name = data.get('name')
            if name == 'patch':
                # TODO: we should do this in a separate thread
                Listener.apply_patch(data)
            elif name == 'get_buf':
                Listener.update_buf(data['id'], data['path'], data['buf'], data['md5'], save=True)
            elif name == 'room_info':
                if self.on_connect:
                    self.on_connect(self)
                    self.on_connect = None
                # Success! Reset counter
                self.retries = G.MAX_RETRIES
                perms = data['perms']
                if 'patch' not in perms:
                    print("We don't have patch permission. Setting buffers to read-only")
                    G.READ_ONLY = True
                project_json = {
                    'folders': [
                        {'path': G.PROJECT_PATH}
                    ]
                }
                try:
                    os.makedirs(G.PROJECT_PATH)
                except Exception:
                    pass
                project_fd = open(os.path.join(G.PROJECT_PATH, '.sublime-project'), 'w')
                project_fd.write(json.dumps(project_json, indent=4, sort_keys=True))
                project_fd.close()
                # TODO: this is hard. ST2 has no project api
#                sublime.active_window().run_command('open', {'file': G.PROJECT_PATH})

                for buf_id, buf in data['bufs'].iteritems():
                    Listener.update_buf(buf_id, buf['path'], "", buf['md5'])
                    # Total hack. apparently we can't create views and set their text in the same "tick"
                    Listener.get_buf(buf_id)

                self.authed = True
            elif name == 'join':
                print('%s joined the room' % data['username'])
            elif name == 'part':
                print('%s left the room' % data['username'])
                region_key = 'floobits-highlight-%s' % (data['user_id'])
                for window in sublime.windows():
                    for view in window.views():
                        view.erase_regions(region_key)
            elif name == 'highlight':
                region_key = 'floobits-highlight-%s' % (data['user_id'])
                Listener.highlight(data['id'], region_key, data['username'], data['ranges'])
            elif name == 'error':
                sublime.error_message('Floobits: Error! Message: %s' % str(data.get('msg')))
            elif name == 'disconnect':
                sublime.error_message('Floobits: Disconnected! Reason: %s' % str(data.get('reason')))
                self.retries = 0
            elif name == 'msg':
                self.chat(data['username'], data['time'], data.get('data'))
            else:
                print('unknown name!', name, 'data:', data)
            self.buf = after

    def select(self):
        if not self.sock:
            print('no sock')
            self.reconnect()
            return

        if not settings.get('run', True):
            return sublime.set_timeout(self.select, 1000)
        # this blocks until the socket is readable or writeable
        _in, _out, _except = select.select([self.sock], [self.sock], [self.sock])

        if _except:
            print('socket error')
            self.sock.close()
            self.reconnect()
            return

        if _in:
            buf = ''
            while True:
                try:
                    d = self.sock.recv(4096)
                    if not d:
                        break
                    buf += d
                except socket.error:
                    break
            if not buf:
                print('buf is empty')
                return self.reconnect()
            self.protocol(buf)

        if _out:
            for p in self.get_patches():
                if p is None:
                    SOCKET_Q.task_done()
                    continue
                print('writing patch: %s' % p)
                self.sock.sendall(p)
                SOCKET_Q.task_done()

        sublime.set_timeout(self.select, 100)

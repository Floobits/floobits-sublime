import os
import json
import socket
import queue
import time
import select
import collections
try:
    import ssl
except ImportError:
    ssl = False

import sublime

from . import shared as G
from . import utils
from . import listener
from . import msg

Listener = listener.Listener

settings = sublime.load_settings('Floobits.sublime-settings')

CHAT_VIEW = None
SOCKET_Q = queue.Queue()

CERT = os.path.join(os.getcwd(), 'startssl-ca.pem')


class AgentConnection(object):
    ''' Simple chat server using select '''
    def __init__(self, owner, room, host=None, port=None, secure=True, on_connect=None):
        self.sock = None
        self.buf = ''
        self.reconnect_delay = G.INITIAL_RECONNECT_DELAY
        self.username = G.USERNAME
        self.secret = G.SECRET
        self.authed = False
        self.host = host or G.DEFAULT_HOST
        self.port = port or G.DEFAULT_PORT
        self.secure = secure
        self.owner = owner
        self.room = room
        self.retries = G.MAX_RETRIES
        self.on_connect = on_connect
        self.chat_deck = collections.deque(maxlen=10)
        self.empty_selects = 0

    def stop(self):
        msg.log('Disconnecting from room %s/%s' % (self.owner, self.room))
        try:
            self.retries = -1
            self.sock.shutdown(2)
            self.sock.close()
        except Exception:
            pass
        msg.log('Disconnected.')

    def send_msg(self, msg):
        self.put(json.dumps({'name': 'msg', 'data': msg}))
        self.chat(self.username, time.time(), msg, True)

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
            msg.debug('%s items in q' % qsize)

    def reconnect(self):
        try:
            self.sock.close()
        except Exception:
            pass
        G.CONNECTED = False
        self.buf = ''
        self.sock = None
        self.authed = False
        self.reconnect_delay *= 1.5
        if self.reconnect_delay > 10000:
            self.reconnect_delay = 10000
        if self.retries > 0:
            msg.log('Floobits: Reconnecting in %sms' % self.reconnect_delay)
            sublime.set_timeout(self.connect, int(self.reconnect_delay))
        elif self.retries == 0:
            sublime.error_message('Floobits Error! Too many reconnect failures. Giving up.')
        self.retries -= 1

    def connect(self):
        self.empty_selects = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if self.secure:
            if ssl:  # ST2 on linux doesn't have the ssl module. Not sure about windows
                self.sock = ssl.wrap_socket(self.sock, ca_certs=CERT, cert_reqs=ssl.CERT_REQUIRED)
            else:
                msg.log('No SSL module found. Connection will not be encrypted.')
                if self.port == G.DEFAULT_PORT:
                    self.port = 3148  # plaintext port
        msg.log('Connecting to %s:%s' % (self.host, self.port))
        try:
            self.sock.settimeout(30)  # Seconds before timing out connecting
            self.sock.connect((self.host, self.port))
            if self.secure and ssl:
                self.sock.do_handshake()
        except socket.error as e:
            msg.error('Error connecting:', e)
            self.reconnect()
            return
        self.sock.setblocking(False)
        msg.log('Connected!')
        self.reconnect_delay = G.INITIAL_RECONNECT_DELAY
        sublime.set_timeout(self.select, 0)
        self.auth()

    def auth(self):
        global SOCKET_Q
        # TODO: we shouldn't throw away all of this
        SOCKET_Q = queue.Queue()
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
            except queue.Empty:
                break

    def chat(self, username, timestamp, message, self_msg=False):
        envelope = msg.MSG(message, timestamp, username)
        if not self_msg:
            self.chat_deck.appendleft(envelope)
        envelope.display()

    def on_msg(self, data):
        message = data.get('data')
        self.chat(data['username'], data['time'], message)
        window = G.ROOM_WINDOW

        def cb(selected):
            if selected == -1:
                return
            envelope = self.chat_deck[selected]
            window.run_command('floobits_prompt_msg', {'msg': '%s: ' % envelope.username})

        if G.ALERT_ON_MSG and message.find(self.username) >= 0:
            window.show_quick_panel([str(x) for x in self.chat_deck], cb)

    def protocol(self, req):
        self.buf += req.decode('utf-8')
        msg.debug('buf: %s' % self.buf)
        while True:
            before, sep, after = self.buf.partition('\n')
            if not sep:
                break
            try:
                data = json.loads(before)
            except Exception as e:
                msg.error('Unable to parse json: %s' % str(e))
                msg.error('Data: %s' % before)
                raise e
            name = data.get('name')
            if name == 'patch':
                # TODO: we should do this in a separate thread
                Listener.apply_patch(data)
            elif name == 'get_buf':
                buf_id = data['id']
                listener.BUFS[buf_id] = data
                view = listener.get_view(buf_id)
                if view:
                    Listener.update_view(data, view)
                else:
                    listener.save_buf(data)
            elif name == 'create_buf':
                listener.BUFS[data['id']] = data
                listener.save_buf(data)
                listener.create_view(data)
            elif name == 'rename_buf':
                new = utils.get_full_path(data['path'])
                old = utils.get_full_path(data['old_path'])
                new_dir = os.path.split(new)[0]
                if new_dir:
                    utils.mkdir(new_dir)
                os.rename(old, new)
                view = listener.get_view(data['id'])
                if view:
                    view.retarget(new)
            elif name == 'delete_buf':
                path = utils.get_full_path(data['path'])
                utils.rm(path)
                listener.delete_buf(data['id'])
            elif name == 'room_info':
                # Success! Reset counter
                self.retries = G.MAX_RETRIES
                perms = data['perms']

                if 'patch' not in perms:
                    msg.log('We don\'t have patch permission. Setting buffers to read-only')
                    G.READ_ONLY = True

                project_json = {
                    'folders': [
                        {'path': G.PROJECT_PATH}
                    ]
                }

                utils.mkdir(G.PROJECT_PATH)
                with open(os.path.join(G.PROJECT_PATH, '.sublime-project'), 'w') as project_fd:
                    project_fd.write(json.dumps(project_json, indent=4, sort_keys=True))

                for buf_id, buf in data['bufs'].items():
                    buf_id = int(buf_id)  # json keys must be strings
                    new_dir = os.path.split(utils.get_full_path(buf['path']))[0]
                    utils.mkdir(new_dir)
                    listener.BUFS[buf_id] = buf
                    Listener.get_buf(buf_id)

                self.authed = True
                G.CONNECTED = True
                msg.log('Successfully joined room %s/%s' % (self.owner, self.room))
                if self.on_connect:
                    self.on_connect(self)
                    self.on_connect = None
            elif name == 'join':
                msg.log('%s joined the room' % data['username'])
            elif name == 'part':
                msg.log('%s left the room' % data['username'])
                region_key = 'floobits-highlight-%s' % (data['user_id'])
                for window in sublime.windows():
                    for view in window.views():
                        view.erase_regions(region_key)
            elif name == 'highlight':
                region_key = 'floobits-highlight-%s' % (data['user_id'])
                Listener.highlight(data['id'], region_key, data['username'], data['ranges'])
            elif name == 'error':
                message = 'Floobits: Error! Message: %s' % str(data.get('msg'))
                msg.error(message)
                sublime.error_message(message)
            elif name == 'disconnect':
                message = 'Floobits: Disconnected! Reason: %s' % str(data.get('reason'))
                msg.error(message)
                sublime.error_message(message)
                self.stop()
            elif name == 'msg':
                self.on_msg(data)
            else:
                msg.error('unknown name!', name, 'data:', data)
            self.buf = after

    def select(self):
        if not self.sock:
            msg.error('select(): No socket.')
            return self.reconnect()

        try:
            # this blocks until the socket is readable or writeable
            _in, _out, _except = select.select([self.sock], [self.sock], [self.sock])
        except (select.error, socket.error) as e:
            msg.error('Error in select(): %s' % str(e))
            return self.reconnect()

        if _except:
            msg.error('Socket error')
            return self.reconnect()

        if _in:
            buf = bytes('', 'utf-8')
            while True:
                try:
                    d = self.sock.recv(4096)
                    if not d:
                        break
                    buf += d
                except (socket.error, TypeError):
                    break

            if buf:
                self.empty_selects = 0
                self.protocol(buf)
            else:
                self.empty_selects += 1
                if self.empty_selects > 5:
                    msg.error('No data from sock.recv() {0} times.'.format(self.empty_selects))
                    return self.reconnect()

        if _out:
            for p in self.get_patches():
                if p is None:
                    SOCKET_Q.task_done()
                    continue
                try:
                    msg.debug('writing patch: %s' % p)
                    self.sock.sendall(bytes(p, 'utf-8'))
                    SOCKET_Q.task_done()
                except Exception as e:
                    msg.error('Couldn\'t write to socket: %s' % str(e))
                    return self.reconnect()

        sublime.set_timeout(self.select, 100)

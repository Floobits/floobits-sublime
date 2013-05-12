import os
import sys
import hashlib
import json
import socket
try:
    import queue
    assert queue
except ImportError:
    import Queue as queue
import imp
import time
import select
import collections

import sublime

try:
    import ssl
    assert ssl
except ImportError:
    ssl = False

try:
    from . import listener, msg, shared as G, utils
    assert G and listener and msg and utils
except ImportError:
    import shared as G
    import utils
    import listener
    import msg

Listener = listener.Listener

settings = sublime.load_settings('Floobits.sublime-settings')

CHAT_VIEW = None
SOCKET_Q = queue.Queue()

if ssl is False and sublime.platform() == 'linux':
    _ssl = None
    ssl_versions = ['0.9.8', '1.0.0', '10']
    ssl_path = os.path.join(G.PLUGIN_PATH, 'lib', 'linux')
    lib_path = os.path.join(G.PLUGIN_PATH, 'lib', 'linux-%s' % sublime.arch())
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
            print('Failed loading _ssl module %s: %s' % (so_path, str(e)))
    if _ssl:
        print('Hooray! %s is a winner!' % so_path)
        filename, path, desc = imp.find_module('ssl', [ssl_path])
        if filename is None:
            print("Couldn't find ssl module at %s" % ssl_path)
        else:
            try:
                ssl = imp.load_module('ssl', filename, path, desc)
            except ImportError as e:
                print('Failed loading ssl module at: %s' % str(e))
    else:
        print("Couldn't find an _ssl shared lib that's compatible with your version of linux. Sorry :(")


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
        self.room_info = {}

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
        self.put({'name': 'msg', 'data': msg})
        self.chat(self.username, time.time(), msg, True)

    def is_ready(self):
        return self.authed

    @staticmethod
    def put(item):
        if not item:
            return
        SOCKET_Q.put(json.dumps(item) + '\n')
        qsize = SOCKET_Q.qsize()
        if qsize > 0:
            msg.debug('%s items in q' % qsize)

    def reconnect(self):
        try:
            self.sock.close()
        except Exception:
            pass
        G.CONNECTED = False
        self.room_info = {}
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
            if ssl:  # ST3 on linux doesn't have the ssl module. OS X & Windows are OK.
                cert = os.path.join(G.PLUGIN_PATH, 'startssl-ca.pem')
                self.sock = ssl.wrap_socket(self.sock, ca_certs=cert, cert_reqs=ssl.CERT_REQUIRED)
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
        if sys.version_info < (3, 0):
            sublime_version = 2
        else:
            sublime_version = 3
        self.put({
            'username': self.username,
            'secret': self.secret,
            'room': self.room,
            'room_owner': self.owner,
            'client': 'SublimeText-%s' % sublime_version,
            'platform': sys.platform,
            'version': G.__VERSION__
        })

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
                try:
                    utils.rm(path)
                except Exception:
                    pass
                listener.delete_buf(data['id'])
            elif name == 'room_info':
                # Success! Reset counter
                self.retries = G.MAX_RETRIES
                self.room_info = data
                G.PERMS = data['perms']

                if 'patch' not in data['perms']:
                    msg.log('We don\'t have patch permission. Setting buffers to read-only')

                project_json = {
                    'folders': [
                        {'path': G.PROJECT_PATH}
                    ]
                }

                utils.mkdir(G.PROJECT_PATH)
                with open(os.path.join(G.PROJECT_PATH, '.sublime-project'), 'wb') as project_fd:
                    project_fd.write(json.dumps(project_json, indent=4, sort_keys=True).encode('utf-8'))

                floo_json = {
                    'url': utils.to_room_url({
                        'host': self.host,
                        'owner': self.owner,
                        'port': self.port,
                        'room': self.room,
                        'secure': self.secure,
                    })
                }
                with open(os.path.join(G.PROJECT_PATH, '.floo'), 'w') as floo_fd:
                    floo_fd.write(json.dumps(floo_json, indent=4, sort_keys=True))

                for buf_id, buf in data['bufs'].items():
                    buf_id = int(buf_id)  # json keys must be strings
                    buf_path = utils.get_full_path(buf['path'])
                    new_dir = os.path.dirname(buf_path)
                    utils.mkdir(new_dir)
                    listener.BUFS[buf_id] = buf
                    try:
                        buf_fd = open(buf_path, 'rb')
                        buf_buf = buf_fd.read().decode('utf-8')
                        md5 = hashlib.md5(buf_buf.encode('utf-8')).hexdigest()
                        if md5 == buf['md5']:
                            msg.debug('md5 sums match. not getting buffer')
                            buf['buf'] = buf_buf
                        else:
                            msg.debug('md5 for %s should be %s but is %s. getting buffer' % (buf['path'], buf['md5'], md5))
                            raise Exception('different md5')
                    except Exception as e:
                        msg.debug('Error calculating md5:', e)
                        Listener.get_buf(buf_id)

                self.authed = True
                G.CONNECTED = True
                msg.log('Successfully joined room %s/%s' % (self.owner, self.room))
                if self.on_connect:
                    self.on_connect(self)
                    self.on_connect = None
            elif name == 'join':
                msg.log('%s joined the room' % data['username'])
                self.room_info['users'][data['user_id']] = data['username']
            elif name == 'part':
                msg.log('%s left the room' % data['username'])
                try:
                    del self.room_info['users'][data['user_id']]
                except Exception as e:
                    print('Unable to delete user %s from user list' % (data))
                region_key = 'floobits-highlight-%s' % (data['user_id'])
                for window in sublime.windows():
                    for view in window.views():
                        view.erase_regions(region_key)
            elif name == 'highlight':
                region_key = 'floobits-highlight-%s' % (data['user_id'])
                Listener.highlight(data['id'], region_key, data['username'], data['ranges'], data.get('ping', False))
            elif name == 'error':
                message = 'Floobits: Error! Message: %s' % str(data.get('msg'))
                msg.error(message)
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
        except (select.error, socket.error, Exception) as e:
            msg.error('Error in select(): %s' % str(e))
            return self.reconnect()

        if _except:
            msg.error('Socket error')
            return self.reconnect()

        if _in:
            buf = ''.encode('utf-8')
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
                if self.empty_selects > 10:
                    msg.error('No data from sock.recv() {0} times.'.format(self.empty_selects))
                    return self.reconnect()

        if _out:
            for p in self.get_patches():
                if p is None:
                    SOCKET_Q.task_done()
                    continue
                try:
                    msg.debug('writing patch: %s' % p)
                    self.sock.sendall(p.encode('utf-8'))
                    SOCKET_Q.task_done()
                except Exception as e:
                    msg.error('Couldn\'t write to socket: %s' % str(e))
                    return self.reconnect()

        sublime.set_timeout(self.select, 100)

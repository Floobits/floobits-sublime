import os
import sys
import hashlib
import json
import socket
import time
import select
import collections
import base64
import errno

import sublime

try:
    import ssl
    assert ssl
except ImportError:
    ssl = False

try:
    from . import cert, listener, msg, shared as G, utils
    assert cert and G and listener and msg and utils
except (ImportError, ValueError):
    import cert
    import shared as G
    import utils
    import listener
    import msg

Listener = listener.Listener

settings = sublime.load_settings('Floobits.sublime-settings')
CHAT_VIEW = None
SOCKET_Q = collections.deque()

try:
    connect_errno = (errno.WSAEWOULDBLOCK, errno.WSAEALREADY, errno.WSAEINVAL)
    iscon_errno = errno.WSAEISCONN
except Exception:
    connect_errno = (errno.EINPROGRESS, errno.EALREADY)
    iscon_errno = errno.EISCONN


class AgentConnection(object):
    ''' Simple chat server using select '''
    MAX_RETRIES = 20
    INITIAL_RECONNECT_DELAY = 500

    def __init__(self, owner, workspace, host=None, port=None, secure=True, on_connect=None):
        self.sock = None
        self.buf = bytes()
        self.reconnect_delay = self.INITIAL_RECONNECT_DELAY
        self.retries = self.MAX_RETRIES
        self.reconnect_timeout = None
        self.username = G.USERNAME
        self.secret = G.SECRET
        self.host = host or G.DEFAULT_HOST
        self.port = port or G.DEFAULT_PORT
        self.secure = secure
        self.owner = owner
        self.workspace = workspace

        self.on_connect = on_connect
        self.chat_deck = collections.deque(maxlen=10)
        self.empty_selects = 0
        self.workspace_info = {}
        self.handshaken = False
        self.cert_path = os.path.join(G.BASE_DIR, 'startssl-ca.pem')
        self.call_select = False

    @property
    def workspace_url(self):
        protocol = self.secure and 'https' or 'http'
        return "{protocol}://{host}/r/{owner}/{name}".format(protocol=protocol, host=self.host, owner=self.owner, name=self.workspace)

    def cleanup(self):
        try:
            self.sock.shutdown(2)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
        G.CONNECTED = False
        self.call_select = False
        self.handshaken = False
        self.workspace_info = {}
        self.buf = bytes()
        self.sock = None

    def stop(self):
        msg.log('Disconnecting from workspace %s/%s' % (self.owner, self.workspace))
        self.retries = -1
        utils.cancel_timeout(self.reconnect_timeout)
        self.reconnect_timeout = None
        self.cleanup()
        msg.log('Disconnected.')

    def send_msg(self, msg):
        self.put({'name': 'msg', 'data': msg})
        self.chat(self.username, time.time(), msg, True)

    def is_ready(self):
        return G.CONNECTED

    @staticmethod
    def put(item):
        if not item:
            return
        msg.debug('writing %s: %s' % (item.get('name', 'NO NAME'), item))
        SOCKET_Q.append(json.dumps(item) + '\n')
        qsize = len(SOCKET_Q)
        if qsize > 0:
            msg.debug('%s items in q' % qsize)

    def reconnect(self):
        if self.reconnect_timeout:
            return
        self.cleanup()
        self.reconnect_delay = min(10000, int(1.5 * self.reconnect_delay))

        if self.retries > 0:
            msg.log('Floobits: Reconnecting in %sms' % self.reconnect_delay)
            self.reconnect_timeout = utils.set_timeout(self.connect, self.reconnect_delay)
        elif self.retries == 0:
            sublime.error_message('Floobits Error! Too many reconnect failures. Giving up.')
        self.retries -= 1

    # All of this craziness is necessary to work-around a Python 2.6 bug: http://bugs.python.org/issue11326
    def _connect(self, attempts=0):
        if attempts > 500:
            msg.error('Connection attempt timed out.')
            return self.reconnect()
        if not self.sock:
            msg.debug('_connect: No socket')
            return
        try:
            self.sock.connect((self.host, self.port))
            select.select([self.sock], [self.sock], [], 0)
        except socket.error as e:
            if e.errno == iscon_errno:
                pass
            elif e.errno in connect_errno:
                return utils.set_timeout(self._connect, 20, attempts + 1)
            else:
                msg.error('Error connecting:', e)
                return self.reconnect()
        if self.secure:
            self.sock = ssl.wrap_socket(self.sock, ca_certs=self.cert_path, cert_reqs=ssl.CERT_REQUIRED, do_handshake_on_connect=False)
        self.auth()
        self.call_select = True
        self.select()

    def connect(self):
        utils.cancel_timeout(self.reconnect_timeout)
        self.reconnect_timeout = None
        self.cleanup()

        self.empty_selects = 0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(False)
        if self.secure:
            if ssl:
                with open(self.cert_path, 'wb') as cert_fd:
                    cert_fd.write(cert.CA_CERT.encode('utf-8'))
            else:
                msg.log('No SSL module found. Connection will not be encrypted.')
                self.secure = False
                if self.port == G.DEFAULT_PORT:
                    self.port = 3148  # plaintext port
        msg.log('Connecting to %s:%s' % (self.host, self.port))
        self._connect()

    def auth(self):
        SOCKET_Q.clear()
        if sys.version_info < (3, 0):
            sublime_version = 2
        else:
            sublime_version = 3
        self.put({
            'username': self.username,
            'secret': self.secret,
            'room': self.workspace,
            'room_owner': self.owner,
            'client': 'SublimeText-%s' % sublime_version,
            'platform': sys.platform,
            'supported_encodings': ['utf8', 'base64'],
            'version': G.__VERSION__
        })

    def get_patches(self):
        try:
            while True:
                yield SOCKET_Q.popleft()
        except IndexError:
            raise StopIteration()

    def chat(self, username, timestamp, message, self_msg=False):
        envelope = msg.MSG(message, timestamp, username)
        if not self_msg:
            self.chat_deck.appendleft(envelope)
        envelope.display()

    def on_msg(self, data):
        message = data.get('data')
        self.chat(data['username'], data['time'], message)
        window = G.WORKSPACE_WINDOW

        def cb(selected):
            if selected == -1:
                return
            envelope = self.chat_deck[selected]
            window.run_command('floobits_prompt_msg', {'msg': '%s: ' % envelope.username})

        if G.ALERT_ON_MSG and message.find(self.username) >= 0:
            window.show_quick_panel([str(x) for x in self.chat_deck], cb)

    def protocol(self, req):
        self.buf += req
        while True:
            before, sep, after = self.buf.partition('\n'.encode('utf-8'))
            if not sep:
                break
            try:
                before = before.decode('utf-8')
                data = json.loads(before)
            except Exception as e:
                msg.error('Unable to parse json: %s' % str(e))
                msg.error('Data: %s' % before)
                raise e
            name = data.get('name')
            if name == 'patch':
                Listener.apply_patch(data)
            elif name == 'get_buf':
                buf_id = data['id']
                buf = listener.BUFS.get(buf_id)
                if not buf:
                    return msg.warn("no buf found: %s.  Hopefully you didn't need that" % data)
                timeout_id = buf.get('timeout_id')
                if timeout_id:
                    utils.cancel_timeout(timeout_id)

                if data['encoding'] == 'base64':
                    data['buf'] = base64.b64decode(data['buf'])
                # forced_patch doesn't exist in data, so this is equivalent to buf['forced_patch'] = False
                listener.BUFS[buf_id] = data
                view = listener.get_view(buf_id)
                if view:
                    Listener.update_view(data, view)
                else:
                    listener.save_buf(data)
            elif name == 'create_buf':
                if data['encoding'] == 'base64':
                    data['buf'] = base64.b64decode(data['buf'])
                listener.BUFS[data['id']] = data
                listener.PATHS_TO_IDS[data['path']] = data['id']
                listener.save_buf(data)
            elif name == 'rename_buf':
                del listener.PATHS_TO_IDS[data['old_path']]
                listener.PATHS_TO_IDS[data['path']] = data['id']
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
                Listener.reset()
                G.CONNECTED = True
                # Success! Reset counter
                self.reconnect_delay = self.INITIAL_RECONNECT_DELAY
                self.retries = self.MAX_RETRIES

                self.workspace_info = data
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
                    'url': utils.to_workspace_url({
                        'host': self.host,
                        'owner': self.owner,
                        'port': self.port,
                        'workspace': self.workspace,
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
                    listener.PATHS_TO_IDS[buf['path']] = buf_id
                    view = listener.get_view(buf_id)
                    if view and not view.is_loading() and buf['encoding'] == 'utf8':
                        view_text = listener.get_text(view)
                        view_md5 = hashlib.md5(view_text.encode('utf-8')).hexdigest()
                        if view_md5 == buf['md5']:
                            msg.debug('md5 sum matches view. not getting buffer %s' % buf['path'])
                            buf['buf'] = view_text
                            G.VIEW_TO_HASH[view.buffer_id()] = view_md5
                        else:
                            Listener.get_buf(buf_id)
                    else:
                        try:
                            buf_fd = open(buf_path, 'rb')
                            buf_buf = buf_fd.read()
                            md5 = hashlib.md5(buf_buf).hexdigest()
                            if md5 == buf['md5']:
                                msg.debug('md5 sum matches. not getting buffer %s' % buf['path'])
                                if buf['encoding'] == 'utf8':
                                    buf_buf = buf_buf.decode('utf-8')
                                buf['buf'] = buf_buf
                            else:
                                Listener.get_buf(buf_id)
                        except Exception as e:
                            msg.debug('Error calculating md5:', e)
                            Listener.get_buf(buf_id)

                msg.log('Successfully joined workspace %s/%s' % (self.owner, self.workspace))

                temp_data = data.get('temp_data', {})
                hangout = temp_data.get('hangout', {})
                hangout_url = hangout.get('url')
                if hangout_url:
                    self.prompt_join_hangout(hangout_url)

                if self.on_connect:
                    self.on_connect()
                    self.on_connect = None
            elif name == 'user_info':
                user_id = str(data['user_id'])
                self.workspace_info['users'][user_id] = data
                # TODO: check if user id is ours and update our perms, etc
            elif name == 'join':
                msg.log('%s joined the workspace' % data['username'])
                user_id = str(data['user_id'])
                self.workspace_info['users'][user_id] = data
            elif name == 'part':
                msg.log('%s left the workspace' % data['username'])
                user_id = str(data['user_id'])
                try:
                    del self.workspace_info['users'][user_id]
                except Exception as e:
                    print('Unable to delete user %s from user list' % (data))
                region_key = 'floobits-highlight-%s' % (user_id)
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
            elif name == 'set_temp_data':
                hangout_data = data.get('data', {})
                hangout = hangout_data.get('hangout', {})
                hangout_url = hangout.get('url')
                if hangout_url:
                    self.prompt_join_hangout(hangout_url)
            elif name == 'saved':
                try:
                    username = self.workspace_info['users'][data['user_id']]['username']
                    buf = listener.BUFS[data['id']]
                    msg.log('%s saved buffer %s' % (username, buf['path']))
                except Exception as e:
                    msg.error(str(e))
            elif name == 'request_perms':
                print(data)
                user_id = str(data.get('user_id'))
                try:
                    username = self.workspace_info['users'][user_id]['username']
                except Exception:
                    msg.debug('Unknown user for id %s. Not handling request_perms event.' % user_id)
                    return
                perm_mapping = {
                    'edit_room': 'edit',
                    'admin_room': 'admin',
                }
                perms = data.get('perms')
                perms_str = ''.join([perm_mapping.get(p) for p in perms])
                prompt = 'User %s is requesting %s permission for this room.' % (username, perms_str)
                message = data.get('message')
                if message:
                    prompt += '\n\n%s says: %s' % (username, message)
                prompt += '\n\nDo you want to grant them permission?'
                confirm = bool(sublime.ok_cancel_dialog(prompt))
                if confirm:
                    action = 'add'
                else:
                    action = 'reject'
                self.put({
                    'name': 'perms',
                    'action': action,
                    'user_id': user_id,
                    'perms': perms
                })
            else:
                msg.debug('unknown name!', name, 'data:', data)
            self.buf = after

    def prompt_join_hangout(self, hangout_url):
        hangout_client = None
        users = self.workspace_info.get('users')
        for user_id, user in users.items():
            if user['username'] == G.USERNAME and 'hangout' in user['client']:
                hangout_client = user
                break
        if not hangout_client:
            G.WORKSPACE_WINDOW.run_command('floobits_prompt_hangout', {'hangout_url': hangout_url})

    def select(self):
        if not self.call_select:
            return

        if not self.sock:
            msg.debug('select(): No socket.')
            return self.reconnect()

        try:
            _in, _out, _except = select.select([self.sock], [self.sock], [self.sock], 0)
        except (select.error, socket.error, Exception) as e:
            msg.error('Error in select(): %s' % str(e))
            return self.reconnect()

        if _except:
            msg.error('Socket error')
            return self.reconnect()

        if _out:
            if self.secure and not self.handshaken:
                try:
                    self.sock.do_handshake()
                except ssl.SSLError as e:
                    return
                except Exception as e:
                    msg.error("Error in SSL handshake:", e)
                    return self.reconnect()
                else:
                    self.handshaken = True

            for p in self.get_patches():
                try:
                    self.sock.sendall(p.encode('utf-8'))
                except Exception as e:
                    msg.error('Couldn\'t write to socket: %s' % str(e))
                    return self.reconnect()

        if _in:
            buf = ''.encode('utf-8')
            while True:
                try:
                    d = self.sock.recv(65536)
                    if not d:
                        break
                    buf += d
                except (AttributeError):
                    return self.reconnect()
                except (socket.error, TypeError):
                    break

            if buf:
                self.empty_selects = 0
                self.protocol(buf)
            else:
                self.empty_selects += 1
                if self.empty_selects > (2000 / G.TICK_TIME):
                    msg.error('No data from sock.recv() {0} times.'.format(self.empty_selects))
                    return self.reconnect()

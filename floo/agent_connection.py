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
import getpass
import sublime
import webbrowser

try:
    import ssl
    assert ssl
except ImportError:
    ssl = False

try:
    from .common import api, cert, msg, shared as G, utils
    from . import listener
    assert api and cert and G and listener and msg and utils
except (ImportError, ValueError):
    from common import api, cert, msg, shared as G, utils
    import listener

Listener = listener.Listener

settings = sublime.load_settings('Floobits.sublime-settings')
CHAT_VIEW = None
PY2 = sys.version_info < (3, 0)
SOCKET_Q = collections.deque()

try:
    connect_errno = (errno.WSAEWOULDBLOCK, errno.WSAEALREADY, errno.WSAEINVAL)
    iscon_errno = errno.WSAEISCONN
except Exception:
    connect_errno = (errno.EINPROGRESS, errno.EALREADY)
    iscon_errno = errno.EISCONN

BASE_FLOORC = '''
# Floobits config

# Logs messages to Sublime Text console instead of a special view
#log_to_console 1

# Enables debug mode
#debug 1

'''
NEWLINE = '\n'.encode('utf-8')


def sock_debug(*args, **kwargs):
    if G.SOCK_DEBUG:
        msg.log(*args, **kwargs)


class BaseAgentConnection(object):
    ''' Simple chat server using select '''
    MAX_RETRIES = 20
    INITIAL_RECONNECT_DELAY = 500

    def __init__(self, host=None, port=None, secure=True):
        self.sock = None
        self.buf = bytes()
        self.reconnect_delay = self.INITIAL_RECONNECT_DELAY
        self.retries = self.MAX_RETRIES
        self.reconnect_timeout = None

        self.host = host or G.DEFAULT_HOST
        self.port = port or G.DEFAULT_PORT
        self.secure = secure

        self.empty_selects = 0
        self.status_timeout = 0
        self.handshaken = False
        self.cert_path = os.path.join(G.BASE_DIR, 'startssl-ca.pem')
        self.call_select = False

    @property
    def client(self):
        if PY2:
            sublime_version = 2
        else:
            sublime_version = 3
        return 'SublimeText-%s' % sublime_version

    def cleanup(self):
        try:
            self.sock.shutdown(2)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass
        G.JOINED_WORKSPACE = False
        self.status_timeout = 0
        self.handshaken = False
        self.buf = bytes()
        self.sock = None
        self.call_select = False

    def stop(self):
        self.retries = -1
        utils.cancel_timeout(self.reconnect_timeout)
        self.reconnect_timeout = None
        self.cleanup()
        msg.log('Disconnected.')
        sublime.status_message('Disconnected.')

    def is_ready(self):
        return False

    @staticmethod
    def put(item):
        if not item:
            return
        msg.debug('writing %s: %s' % (item.get('name', 'NO NAME'), item))
        SOCKET_Q.append(json.dumps(item) + '\n')
        qsize = len(SOCKET_Q)
        if qsize > 0:
            msg.debug('%s items in q' % qsize)
        return qsize

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
            sock_debug('SSL-wrapping socket')
            self.sock = ssl.wrap_socket(self.sock, ca_certs=self.cert_path, cert_reqs=ssl.CERT_REQUIRED, do_handshake_on_connect=False)

        self.on_connect()
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
        conn_msg = 'Connecting to %s:%s' % (self.host, self.port)
        msg.log(conn_msg)
        sublime.status_message(conn_msg)
        self._connect()

    def protocol(self, req):
        self.buf += req
        while True:
            before, sep, after = self.buf.partition(NEWLINE)
            if not sep:
                break
            try:
                # Node.js sends invalid utf8 even though we're calling write(string, "utf8")
                # Python 2 can figure it out, but python 3 hates it and will die here with some byte sequences
                # Instead of crashing the plugin, we drop the data. Yes, this is horrible.
                before = before.decode('utf-8', 'ignore')
                data = json.loads(before)
            except Exception as e:
                msg.error('Unable to parse json: %s' % str(e))
                msg.error('Data: %s' % before)
                # XXXX: THIS LOSES DATA
                self.buf = after
                continue
            name = data.get('name')
            try:
                if name == 'error':
                    message = 'Floobits: Error! Message: %s' % str(data.get('msg'))
                    msg.error(message)
                    if data.get('flash'):
                        sublime.error_message('Floobits: %s' % str(data.get('msg')))
                elif name == 'disconnect':
                    message = 'Floobits: Disconnected! Reason: %s' % str(data.get('reason'))
                    msg.error(message)
                    sublime.error_message(message)
                    self.stop()
                else:
                    self.handler(name, data)
            except Exception as e:
                msg.error('Error handling %s event with data %s: %s' % (name, data, e))
                if name == 'room_info':
                    sublime.error_message('Error joining workspace: %s' % str(e))
                    self.stop()
            self.buf = after

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
            sock_debug('Socket is writeable')
            if self.secure and not self.handshaken:
                try:
                    sock_debug('Doing SSL handshake')
                    self.sock.do_handshake()
                except ssl.SSLError as e:
                    sock_debug('ssl.SSLError. This is expected sometimes.')
                    return
                except Exception as e:
                    msg.error('Error in SSL handshake:', e)
                    return self.reconnect()
                else:
                    self.handshaken = True
                    sock_debug('Successful handshake')

            try:
                while True:
                    p = SOCKET_Q.popleft()
                    sock_debug('sending patch')
                    self.sock.sendall(p.encode('utf-8'))
            except IndexError:
                sock_debug('Done writing for now')
            except Exception as e:
                msg.error('Couldn\'t write to socket: %s' % str(e))
                return self.reconnect()

        if _in:
            sock_debug('Socket is readable')
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
                sock_debug('read data')
                self.protocol(buf)
            else:
                sock_debug('empty select')
                self.empty_selects += 1
                if self.empty_selects > (2000 / G.TICK_TIME):
                    msg.error('No data from sock.recv() {0} times.'.format(self.empty_selects))
                    return self.reconnect()
            sock_debug('Done reading for now')

        self.status_timeout += 1
        if self.status_timeout > (2000 / G.TICK_TIME):
            sublime.status_message('Connected to %s::%s' % (self.owner, self.workspace))
            self.status_timeout = 0


class AgentConnection(BaseAgentConnection):
    def __init__(self, owner, workspace, on_room_info, get_bufs=True, **kwargs):
        super(AgentConnection, self).__init__(**kwargs)

        self.owner = owner
        self.workspace = workspace
        self.on_room_info = on_room_info
        self.get_bufs = get_bufs
        self.chat_deck = collections.deque(maxlen=10)
        self.workspace_info = {}
        self.reload_settings()

    @property
    def workspace_url(self):
        protocol = self.secure and 'https' or 'http'
        return '{protocol}://{host}/r/{owner}/{name}'.format(protocol=protocol, host=self.host, owner=self.owner, name=self.workspace)

    def is_ready(self):
        return G.JOINED_WORKSPACE

    def reload_settings(self):
        utils.reload_settings()
        self.username = G.USERNAME
        self.secret = G.SECRET
        self.api_key = G.API_KEY

    def on_connect(self):
        SOCKET_Q.clear()

        self.reload_settings()

        req = {
            'username': self.username,
            'secret': self.secret,
            'room': self.workspace,
            'room_owner': self.owner,
            'client': self.client,
            'platform': sys.platform,
            'supported_encodings': ['utf8', 'base64'],
            'version': G.__VERSION__
        }

        if self.api_key:
            req['api_key'] = self.api_key
        self.put(req)

    def stop(self):
        stop_msg = 'Disconnecting from workspace %s/%s' % (self.owner, self.workspace)
        msg.log(stop_msg)
        sublime.status_message(stop_msg)
        super(AgentConnection, self).stop()

    def cleanup(self, *args, **kwargs):
        super(AgentConnection, self).cleanup(*args, **kwargs)
        self.workspace_info = {}

    def send_msg(self, msg):
        self.put({'name': 'msg', 'data': msg})
        self.chat(self.username, time.time(), msg, True)

    def chat(self, username, timestamp, message, self_msg=False):
        envelope = msg.MSG(message, timestamp, username)
        if not self_msg:
            self.chat_deck.appendleft(envelope)
        envelope.display()

    def get_username_by_id(self, user_id):
        try:
            return self.workspace_info['users'][str(user_id)]['username']
        except Exception:
            return ''

    def handler(self, name, data):
        if name == 'patch':
            Listener.apply_patch(data)
        elif name == 'get_buf':
            buf_id = data['id']
            buf = listener.BUFS.get(buf_id)
            if not buf:
                return msg.warn('no buf found: %s.  Hopefully you didn\'t need that' % data)
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
            cb = listener.CREATE_BUF_CBS.get(data['path'])
            if cb:
                del listener.CREATE_BUF_CBS[data['path']]
                try:
                    cb(data['id'])
                except Exception as e:
                    print(e)
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
            listener.BUFS[data['id']]['path'] = data['path']
        elif name == 'delete_buf':
            path = utils.get_full_path(data['path'])
            listener.delete_buf(data['id'])
            try:
                utils.rm(path)
            except Exception:
                pass
            user_id = data.get('user_id')
            username = self.get_username_by_id(user_id)
            msg.log('%s deleted %s' % (username, path))
        elif name == 'room_info':
            Listener.reset()
            G.JOINED_WORKSPACE = True
            # Success! Reset counter
            self.reconnect_delay = self.INITIAL_RECONNECT_DELAY
            self.retries = self.MAX_RETRIES

            self.workspace_info = data
            G.PERMS = data['perms']

            if 'patch' not in data['perms']:
                msg.log('No patch permission. Setting buffers to read-only')
                if sublime.ok_cancel_dialog('You don\'t have permission to edit this workspace. All files will be read-only.\n\nDo you want to request edit permission?'):
                    self.put({'name': 'request_perms', 'perms': ['edit_room']})

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
            utils.update_floo_file(os.path.join(G.PROJECT_PATH, '.floo'), floo_json)

            changed_bufs = []
            missing_bufs = []
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
                    elif self.get_bufs:
                        changed_bufs.append(buf_id)
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
                        elif self.get_bufs:
                            changed_bufs.append(buf_id)
                    except Exception as e:
                        msg.debug('Error calculating md5:', e)
                        missing_bufs.append(buf_id)

            if changed_bufs and self.get_bufs:
                if len(changed_bufs) > 4:
                    prompt = '%s local files are different from the workspace. Overwrite your local files?' % len(changed_bufs)
                else:
                    prompt = 'Overwrite the following local files?\n'
                    for buf_id in changed_bufs:
                        prompt += '\n%s' % listener.BUFS[buf_id]['path']
                stomp_local = sublime.ok_cancel_dialog(prompt)
                for buf_id in changed_bufs:
                    if stomp_local:
                        Listener.get_buf(buf_id)
                    else:
                        buf = listener.BUFS[buf_id]
                        # TODO: this is inefficient. we just read the file 20 lines ago
                        Listener.create_buf(utils.get_full_path(buf['path']))

            for buf_id in missing_bufs:
                Listener.get_buf(buf_id)

            success_msg = 'Successfully joined workspace %s/%s' % (self.owner, self.workspace)
            msg.log(success_msg)
            sublime.status_message(success_msg)

            temp_data = data.get('temp_data', {})
            hangout = temp_data.get('hangout', {})
            hangout_url = hangout.get('url')
            if hangout_url:
                self.prompt_join_hangout(hangout_url)

            if self.on_room_info:
                self.on_room_info()
                self.on_room_info = None
        elif name == 'user_info':
            user_id = str(data['user_id'])
            user_info = data['user_info']
            self.workspace_info['users'][user_id] = user_info
            if user_id == str(self.workspace_info['user_id']):
                G.PERMS = user_info['perms']
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
            Listener.highlight(data['id'], region_key, data['username'], data['ranges'], data.get('ping', False), True)
        elif name == 'set_temp_data':
            hangout_data = data.get('data', {})
            hangout = hangout_data.get('hangout', {})
            hangout_url = hangout.get('url')
            if hangout_url:
                self.prompt_join_hangout(hangout_url)
        elif name == 'saved':
            try:
                buf = listener.BUFS[data['id']]
                username = self.get_username_by_id(data['user_id'])
                msg.log('%s saved buffer %s' % (username, buf['path']))
            except Exception as e:
                msg.error(str(e))
        elif name == 'request_perms':
            print(data)
            user_id = str(data.get('user_id'))
            username = self.get_username_by_id(user_id)
            if not username:
                return msg.debug('Unknown user for id %s. Not handling request_perms event.' % user_id)
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
        elif name == 'perms':
            action = data['action']
            user_id = str(data['user_id'])
            user = self.workspace_info['users'].get(user_id)
            if user is None:
                msg.log('No user for id %s. Not handling perms event' % user_id)
                return
            perms = set(user['perms'])
            if action == 'add':
                perms |= set(data['perms'])
            elif action == 'remove':
                perms -= set(data['perms'])
            else:
                return
            user['perms'] = list(perms)
            if user_id == self.workspace_info['user_id']:
                G.PERMS = perms
        elif name == 'msg':
            self.on_msg(data)
        else:
            msg.debug('unknown name!', name, 'data:', data)

    def prompt_join_hangout(self, hangout_url):
        hangout_client = None
        users = self.workspace_info.get('users')
        for user_id, user in users.items():
            if user['username'] == G.USERNAME and 'hangout' in user['client']:
                hangout_client = user
                break
        if not hangout_client:
            G.WORKSPACE_WINDOW.run_command('floobits_prompt_hangout', {'hangout_url': hangout_url})

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


class RequestCredentialsConnection(BaseAgentConnection):

    def __init__(self, token, **kwargs):
        super(RequestCredentialsConnection, self).__init__(**kwargs)
        self.token = token
        webbrowser.open('https://%s/dash/link_editor/%s/' % (self.host, token))

    def on_connect(self):
        self.put({
            'name': 'request_credentials',
            'client': self.client,
            'platform': sys.platform,
            'token': self.token,
            'version': G.__VERSION__
        })

    def handler(self, name, data):
        if name == 'credentials':
            with open(G.FLOORC_PATH, 'wb') as floorc_fd:
                floorc = BASE_FLOORC + '\n'.join(['%s %s' % (k, v) for k, v in data['credentials'].items()]) + '\n'
                floorc_fd.write(floorc.encode('utf-8'))
            utils.reload_settings()  # This only works because G.JOINED_WORKSPACE is False
            if not G.USERNAME or not G.SECRET:
                sublime.message_dialog('Something went wrong. See https://%s/help/floorc/ to complete the installation.' % self.host)
                api.send_error({'message': 'No username or secret'})
            else:
                p = os.path.join(G.BASE_DIR, 'welcome.md')
                with open(p, 'wb') as fd:
                    text = 'Welcome %s!\n\nYou\'re all set to collaborate. You may want to check out our docs at https://%s/help/plugins/#sublime-usage' % (G.USERNAME, self.host)
                    fd.write(text.encode('utf-8'))
                sublime.active_window().open_file(p)
            self.stop()


welcome_text = 'Welcome %s!\n\nYou\'re all set to collaborate. You should check out our docs at https://%s/help/plugins/#sublime-usage.  \
You must run \'Floobits - Complete Sign Up\' in the command palette before you can login to floobits.com.'


class CreateAccountConnection(BaseAgentConnection):

    def on_connect(self):
        try:
            username = getpass.getuser()
        except:
            username = ''

        self.put({
            'name': 'create_user',
            'username': username,
            'client': self.client,
            'platform': sys.platform,
            'version': G.__VERSION__
        })

    def handler(self, name, data):
        if name == 'create_user':
            del data['name']
            try:
                floorc = BASE_FLOORC + '\n'.join(['%s %s' % (k, v) for k, v in data.items()]) + '\n'
                with open(G.FLOORC_PATH, 'wb') as floorc_fd:
                    floorc_fd.write(floorc.encode('utf-8'))
                utils.reload_settings()
                if False in [bool(x) for x in (G.USERNAME, G.API_KEY, G.SECRET)]:
                    sublime.message_dialog('Something went wrong. You will need to sign up for an account to use Floobits.')
                    api.send_error({'message': 'No username or secret'})
                else:
                    p = os.path.join(G.BASE_DIR, 'welcome.md')
                    with open(p, 'wb') as fd:
                        text = welcome_text % (G.USERNAME, self.host)
                        fd.write(text.encode('utf-8'))
                    d = utils.get_persistent_data()
                    d['auto_generated_account'] = True
                    utils.update_persistent_data(d)
                    G.AUTO_GENERATED_ACCOUNT = True
                    sublime.active_window().open_file(p)
            except Exception as e:
                msg.error(e)
            try:
                d = utils.get_persistent_data()
                d['disable_account_creation'] = True
                utils.update_persistent_data(d)
            finally:
                self.stop()

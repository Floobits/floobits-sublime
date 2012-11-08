# coding: utf-8
import Queue
import threading
import socket
import os
import select
import json
import collections
import os.path
import hashlib
import traceback

import sublime
import sublime_plugin
from lib import diff_match_patch as dmp

__VERSION__ = '0.01'

settings = sublime.load_settings('Floobits.sublime-settings')

COLAB_DIR = ""
def reload_settings():
    global COLAB_DIR
    COLAB_DIR = settings.get('share_dir', '~/.floobits/share/')
    if COLAB_DIR[-1] != '/':
        COLAB_DIR += '/'

settings.add_on_change('', reload_settings)
reload_settings()

SOCKET_Q = Queue.Queue()
BUF_STATE = collections.defaultdict(str)
MODIFIED_EVENTS = Queue.Queue()
BUF_IDS_TO_VIEWS = {}

def get_full_path(p):
    full_path = os.path.join(COLAB_DIR, p)
    return unfuck_path(full_path)


def unfuck_path(p):
    print "unfucking", p
    return os.path.normcase(os.path.normpath(p))


def text(view):
    return view.substr(sublime.Region(0, view.size()))


def get_view_from_path(path):
    for window in sublime.windows():
        for view in window.views():
            file_name = view.file_name()
            if not file_name:
                continue
            view_path = unfuck_path(file_name)
            if view_path == path:
                return view
    return None


class DMP(object):
    def __init__(self, view):
        self.buf_id = None
        self.vb_id = view.buffer_id()
        # to rel path
        self.path = view.file_name()[len(COLAB_DIR):]
        self.current = text(view)
        self.previous = BUF_STATE[self.vb_id]
        for buf_id, vb_id in BUF_IDS_TO_VIEWS.iteritems():
            if vb_id == self.vb_id:
                self.buf_id = buf_id
        if not self.buf_id:
            print("SHIIIIIIIIT")

    def __str__(self):
        return "%s - %s - %s" % (self.buf_id, self.path, self.vb_id)

    def patch(self):
        return dmp.diff_match_patch().patch_make(self.previous, self.current)

    def to_json(self):
        patch = self.patch()
        if len(patch) == 0:
            return None
        elif len(patch) > 1:
            print "WTF!? there are %s patches" % len(patch)
        patch_str = str(patch[0])
        print "patch:", patch_str
        return json.dumps({
                'id': str(self.buf_id),
                'md5': hashlib.md5(self.current).hexdigest(),
                'path': self.path,
                'patch': patch_str,
                'name': 'patch'
            })


class AgentConnection(object):
    """ Simple chat server using select """

    def __init__(self):
        self.sock = None
        self.buf = ""
        self.reconnect_delay = 100
        self.host = settings.get("host", "floobits.com")
        self.port = settings.get("port", 3148)
        self.username = settings.get('username')
        self.secret = settings.get('secret')

    @staticmethod
    def put(item):
        SOCKET_Q.put(item)
        qsize = SOCKET_Q.qsize()
        if qsize > 0:
            print('%s items in q' % qsize)

    def reconnect(self):
        self.sock = None
        self.reconnect_delay *= 1.5
        if self.reconnect_delay > 5000: # 5 seconds
            self.reconnect_delay = 5000
        print "reconnecting in", self.reconnect_delay, ""
        sublime.set_timeout(self.connect, int(self.reconnect_delay))

    def connect(self, room=None):
        if room:
            self.room = room
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((self.host, self.port))
        except socket.error:
            self.reconnect()
            return
        self.sock.setblocking(0)
        print('connected, calling select')
        self.reconnect_delay = 1
        self.select()
        self.auth()

    def auth(self):
        self.put(json.dumps({
            'username': self.username,
            'secret': self.secret,
            'room': self.room,
            'room_owner': self.username,
            'version': __VERSION__
        }))
        # TODO: room_owner can be different from username

    def get_patches(self):
        while True:
            try:
                yield SOCKET_Q.get_nowait()
            except Queue.Empty:
                break

    def protocol(self, req):
        self.buf += req
        while True:
            before, sep, after = self.buf.partition('\n')
            if not sep:
                break
            data = json.loads(before)
            name = data['name']
            if name == 'patch':
                # TODO: we should do this in a separate thread
                Listener.apply_patch(data)
            elif name == 'get_buf':
                Listener.update_buf(data['id'], data['path'], data['buf'], data['md5'])
            elif name == 'room_info':
                # TODO: do something with tree, owner, and users
                for buf_id, buf in data['bufs'].iteritems():
                    print("updating buf", buf['id'])
                    Listener.update_buf(buf['id'], buf['path'], buf['buf'], buf['md5'])
            else:
                print "unknown name!", name
            self.buf = after

    def select(self):
        if not self.sock:
            print('no sock')
            self.reconnect()
            return

        # this blocks until the socket is readable or writeable
        _in, _out, _except = select.select([self.sock], [self.sock], [self.sock])

        if _except:
            print('socket error')
            self.sock.close()
            self.reconnect()
            return

        if _in:
            buf = ""
            while True:
                try:
                    d = self.sock.recv(4096)
                    if not d:
                        break
                    buf += d
                except socket.error:
                    break
            if not buf:
                print "buf is empty"
                return self.reconnect()
            self.protocol(buf)

        if _out:
            for p in self.get_patches():
                if p is None:
                    SOCKET_Q.task_done()
                    continue
                print('writing patch', p)
                self.sock.sendall(p + '\n')
                SOCKET_Q.task_done()

        sublime.set_timeout(self.select, 100)


class Listener(sublime_plugin.EventListener):
    views_changed = []

    @staticmethod
    def push():
        reported = set()
        while Listener.views_changed:
            view = Listener.views_changed.pop()

            vb_id = view.buffer_id()
            if vb_id in reported:
                continue

            reported.add(vb_id)
            patch = DMP(view)
            #update the current copy of the buffer
            BUF_STATE[vb_id] = patch.current
            SOCKET_Q.put(patch.to_json())

        sublime.set_timeout(Listener.push, 100)

    @staticmethod
    def apply_patch(patch_data):
        buf_id = patch_data['id']
        path = get_full_path(patch_data['path'])
        view = BUF_IDS_TO_VIEWS.get(buf_id)
        if not view:
            # maybe we should create a new window? I don't know
            window = sublime.active_window()
            view = window.open_file(path)
            BUF_IDS_TO_VIEWS[buf_id] = view
        DMP = dmp.diff_match_patch()
        if len(patch_data['patch']) == 0:
            print "no patches to apply"
            return
        print "patch is", patch_data['patch']
        dmp_patch = DMP.patch_fromText(patch_data['patch'])
        # TODO: run this in a separate thread
        old_text = text(view)
        t = DMP.patch_apply(dmp_patch, old_text)
        print "t is ", t
        if t[1][0]:
            cur_hash = hashlib.md5(t[0]).hexdigest()
            if cur_hash != patch_data['md5']:
                print "new hash %s != expected %s" % (cur_hash, patch_data['md5'])
                # TODO: do something better than erasing local changes
                return Listener.get_buf(buf_id)
            else:
                Listener.update_buf(buf_id, patch_data['path'], str(t[0]), cur_hash, view)
        else:
            print "failed to patch"
            return Listener.get_buf(buf_id)

    @staticmethod
    def get_buf(buf_id):
        req = {
            'name': 'get_buf',
            'id': buf_id
        }
        SOCKET_Q.put(json.dumps(req))

    @staticmethod
    def update_buf(buf_id, path, text, md5, view=None):
        path = get_full_path(path)
        if not view:
            view = BUF_IDS_TO_VIEWS.get(buf_id)
        if not view:
            # maybe we should create a new window? I don't know
            window = sublime.active_window()
            view = window.open_file(path)
            BUF_IDS_TO_VIEWS[buf_id] = view
        region = sublime.Region(0, view.size())
        selections = [x for x in view.sel()]
        MODIFIED_EVENTS.put(1)
        # so we don't send a patch back to the server for this
        BUF_STATE[view.buffer_id()] = text.decode("utf-8")
        try:
            edit = view.begin_edit()
            view.replace(edit, region, text.decode("utf-8"))
        finally:
            view.end_edit(edit)
        view.sel().clear()
        for sel in selections:
            print "re-adding selection", sel
            view.sel().add(sel)

    def id(self, view):
        return view.buffer_id()

    def name(self, view):
        return view.file_name()

    def on_new(self, view):
        print 'new', self.name(view)

    def on_load(self, view):
        print 'load', self.name(view)

    def on_clone(self, view):
        self.add(view)
        print 'clone', self.name(view)

    def on_modified(self, view):
        try:
            MODIFIED_EVENTS.get_nowait()
        except Queue.Empty:
            self.add(view)
        else:
            MODIFIED_EVENTS.task_done()

    def on_activated(self, view):
        if view.is_scratch():
            return
        self.add(view)
        print 'activated', self.name(view)

    def add(self, view):
        vb_id = view.buffer_id();
        # This could probably be more efficient
        if BUF_IDS_TO_VIEWS.values().count(vb_id) > 0:
            print("view is in BUF_IDS_TO_VIEWS. sending patch")
            self.views_changed.append(view)
        else:
            print("view isn't in BUF_IDS_TO_VIEWS. not sending patch")
        if view.is_scratch():
            print('is scratch')
            return
#        p = unfuck_path(view.file_name() or view.name())
#        print "file_name %s view name %s p %s" % (view.file_name(), view.name(), p)
#        if p.find(COLAB_DIR, 0, len(COLAB_DIR)) == 0:
#            self.views_changed.append(view)
#        else:
#            print "%s isn't in %s. not sending patch" % (COLAB_DIR, p)


class PromptJoinRoomCommand(sublime_plugin.WindowCommand):
    def run(self, *args, **kwargs):
        self.window.show_input_panel("Join room:", "", self.on_input, None, None)

    def on_input(self, room):
        print('room:', room)
        self.window.active_view().run_command("join_room", {"room": room})


class JoinRoomCommand(sublime_plugin.TextCommand):
    def run(self, edit, room):
        def run_agent():
            global AGENT
            try:
                AGENT.connect(room)
            except Exception as e:
                print e
                tb = traceback.format_exc()
                print tb

        thread = threading.Thread(target=run_agent)
        thread.start()


Listener.push()
AGENT = AgentConnection()


import Queue
import threading
import socket
import os
import select
import json
import collections
import os.path
import hashlib

import sublime
import sublime_plugin
from lib import diff_match_patch as dmp

settings = sublime.load_settings('coLab.sublime-settings')

COLAB_DIR = ""
def reload_settings():
    global COLAB_DIR
    COLAB_DIR = settings.get('share_dir', '~/.colab/share')

settings.add_on_change('share_dir', reload_settings)
reload_settings()

PATCH_Q = Queue.Queue()
BUF_STATE = collections.defaultdict(str)
MODIFIED_EVENTS = Queue.Queue()


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
        self.buffer_id = view.buffer_id()
        #to rel path
        self.path = view.file_name()[len(COLAB_DIR):]
        self.current = text(view)
        self.previous = BUF_STATE[self.buffer_id]

    def __str__(self):
        return "%s - %s" % (self.path, self.buffer_id)

    def patch(self):
        return dmp.diff_match_patch().patch_make(self.previous, self.current)

    def to_json(self):
        print "patch", self.patch()
        return json.dumps({
                'uid': str(self.buffer_id),
                'md5': hashlib.md5(self.current).hexdigest(),
                'path': self.path,
                'patch': [str(x) for x in self.patch()]
            })


class AgentConnection(object):
    """ Simple chat server using select """

    def __init__(self):
        self.sock = None
        self.buf = ""

    @staticmethod
    def put(item):
        PATCH_Q.put(item)
        qsize = PATCH_Q.qsize()
        if qsize > 0:
            print('%s items in q' % qsize)

    def reconnect(self):
        self.sock = None
        sublime.set_timeout(self.connect, 100)

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect(('127.0.0.1', 12345))
        except socket.error:
            self.reconnect()
            return
        self.sock.setblocking(0)
        print('connected, calling select')
        self.select()

    def get_patches(self):
        while True:
            try:
                yield PATCH_Q.get_nowait()
            except Queue.Empty:
                break

    def protocol(self, req):
        self.buf += req
        patches = []
        while True:
            before, sep, after = self.buf.partition('\n')
            if not sep:
                break
            patches.append(before)
            self.buf = after
        if patches:
            Listener.apply_patches(patches)
        else:
            print "No patches in", req

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
                print "buf is empty. reconnecting..."
                return self.reconnect()
            self.protocol(buf)

        if _out:
            for patch in self.get_patches():
                p = patch.to_json()
                print('writing a patch', p)
                self.sock.sendall(p + '\n')
                PATCH_Q.task_done()

        sublime.set_timeout(self.select, 100)


class Listener(sublime_plugin.EventListener):
    views_changed = []
    url = 'http://fixtheco.de:3149/patch/'
    uid_to_buf_id = {}

    @staticmethod
    def push():
        reported = set()
        while Listener.views_changed:
            view = Listener.views_changed.pop()

            buf_id = view.buffer_id()
            if buf_id in reported:
                continue

            reported.add(buf_id)
            patch = DMP(view)
            #update the current copy of the buffer
            BUF_STATE[buf_id] = patch.current
            PATCH_Q.put(patch)

        sublime.set_timeout(Listener.push, 100)

    @staticmethod
    def apply_patches(jsons):
        for line in jsons:
            patch_data = json.loads(line)
            path = get_full_path(patch_data['path'])
            view = get_view_from_path(path)
            if not view:
                window = sublime.active_window()
                view = window.open_file(path)
            DMP = dmp.diff_match_patch()
            if len(patch_data['patch']) == 0:
                print "no patches to apply"
                return
            print "patch is", patch_data['patch']
            dmp_patch = DMP.patch_fromText(patch_data['patch'][0])
            # TODO: run this in a separate thread
            old_text = text(view)
            print "old text:", old_text
            t = DMP.patch_apply(dmp_patch, old_text)
            print "t is ", t
            if t[1][0]:
                region = sublime.Region(0, view.size())
                print "region", region
                MODIFIED_EVENTS.put(1)
                try:
                    edit = view.begin_edit()
                    view.replace(edit, region, str(t[0]))
                finally:
                    view.end_edit(edit)
                cur_hash = hashlib.md5(t[0]).hexdigest()
                if cur_hash != patch_data['md5']:
                    print "new hash %s != expected %s" % (cur_hash, patch_data['md5'])
            else:
                print "failed to patch"

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
        if view.is_scratch():
            print('is scratch')
            return
        p = unfuck_path(view.file_name() or view.name())
        print "file_name %s view name %s p %s" % (view.file_name(), view.name(), p)
        print p
        if p.find(COLAB_DIR, 0, len(COLAB_DIR)) == 0:
            self.views_changed.append(view)
        else:
            print "%s isn't in %s. not sending patch" % (COLAB_DIR, p)

class JoinChannelCommand(sublime_plugin.TextCommand):
    def run(self, *args, **kwargs):
        self.get_window().show_input_panel("Channel", "", self.on_input, None, None)
        #self.panel('hawro')

    def on_input(self, channel):
        print('chanel: %s' % channel)
        sublime.status_message('colab chanel: %s' % (channel))

    def active_view(self):
        return self.view

    def is_enabled(self):
        return True

    def get_file_name(self):
        return os.path.basename(self.view.file_name())

    def get_working_dir(self):
        return os.path.dirname(self.view.file_name())

    def get_window(self):
        # Fun discovery: if you switch tabs while a command is working,
        # self.view.window() is None. (Admittedly this is a consequence
        # of my deciding to do async command processing... but, hey,
        # got to live with that now.)
        # I did try tracking the window used at the start of the command
        # and using it instead of view.window() later, but that results
        # panels on a non-visible window, which is especially useless in
        # the case of the quick panel.
        # So, this is not necessarily ideal, but it does work.
        return self.view.window() or sublime.active_window()

    def _output_to_view(self, output_file, output, clear=False, syntax="Packages/JavaScript/JavaScript.tmLanguage"):
        output_file.set_syntax_file(syntax)
        edit = output_file.begin_edit()
        if clear:
            region = sublime.Region(0, self.output_view.size())
            output_file.erase(edit, region)
        output_file.insert(edit, 0, output)
        output_file.end_edit(edit)

    def scratch(self, output, title=False, **kwargs):
        scratch_file = self.get_window().new_file()
        if title:
            scratch_file.set_name(title)
        scratch_file.set_scratch(True)
        self._output_to_view(scratch_file, output, **kwargs)
        scratch_file.set_read_only(True)
        return scratch_file

    def panel(self, output, **kwargs):
        if not hasattr(self, 'output_view'):
            self.output_view = self.get_window().get_output_panel("git")
        self.output_view.set_read_only(False)
        self._output_to_view(self.output_view, output, clear=True, **kwargs)
        self.output_view.set_read_only(True)
        self.get_window().run_command("show_panel", {"panel": "output.git"})

    def quick_panel(self, *args, **kwargs):
        self.get_window().show_quick_panel(*args, **kwargs)

Listener.push()


def run_agent():
    try:
        agent = AgentConnection()
        agent.connect()
    except Exception as e:
        print e

thread = threading.Thread(target=run_agent)
thread.start()

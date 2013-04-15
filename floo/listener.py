import os
import queue
import hashlib
from datetime import datetime

import sublime
import sublime_plugin
from . import dmp_monkey
dmp_monkey.monkey_patch()
from .lib import diff_match_patch as dmp

from . import msg
from . import shared as G
from . import utils

MODIFIED_EVENTS = queue.Queue()
SELECTED_EVENTS = queue.Queue()
BUFS = {}


def get_text(view):
    return view.substr(sublime.Region(0, view.size()))


def get_view(buf_id):
    buf = BUFS[buf_id]
    for view in G.ROOM_WINDOW.views():
        if not view.file_name():
            continue
        if buf['path'] == utils.to_rel_path(view.file_name()):
            return view
    return None


def create_view(buf):
    path = utils.get_full_path(buf['path'])
    view = G.ROOM_WINDOW.open_file(path)
    if view:
        msg.debug('Created view', view.name() or view.file_name())
    return view


def get_buf(view):
    if view.is_scratch():
        return None
    if not view.file_name():
        return None
    if view is G.CHAT_VIEW:
        return None
    rel_path = utils.to_rel_path(view.file_name())
    for buf_id, buf in BUFS.items():
        if rel_path == buf['path']:
            return buf
    return None


def save_buf(buf):
    path = utils.get_full_path(buf['path'])
    utils.mkdir(os.path.split(path)[0])
    with open(path, 'wb') as fd:
        fd.write(buf['buf'].encode('utf-8'))


def delete_buf(buf_id):
    # TODO: somehow tell the user about this. maybe delete on disk too?
    del BUFS[buf_id]


class FlooPatch(object):

    def __init__(self, view, buf):
        self.buf = buf
        self.view = view
        self.current = get_text(view)
        self.previous = buf['buf']
        self.md5_before = hashlib.md5(self.previous.encode('utf-8')).hexdigest()

    def __str__(self):
        return '%s - %s - %s' % (self.buf['id'], self.buf['path'], self.view.buffer_id())

    def patches(self):
        return dmp.diff_match_patch().patch_make(self.previous, self.current)

    def to_json(self):
        patches = self.patches()
        if len(patches) == 0:
            return None
        msg.debug('sending %s patches' % len(patches))
        patch_str = ''
        for patch in patches:
            patch_str += str(patch)
        return {
            'id': self.buf['id'],
            'md5_after': hashlib.md5(self.current.encode('utf-8')).hexdigest(),
            'md5_before': self.md5_before,
            'path': self.buf['path'],
            'patch': patch_str,
            'name': 'patch'
        }


class Listener(sublime_plugin.EventListener):
    views_changed = []
    selection_changed = []
    agent = None

    def __init__(self, *args, **kwargs):
        sublime_plugin.EventListener.__init__(self, *args, **kwargs)
        self.between_save_events = {}

    @staticmethod
    def set_agent(agent):
        Listener.agent = agent

    @staticmethod
    def push():
        reported = set()
        while Listener.views_changed:
            view, buf = Listener.views_changed.pop()
            if view.is_loading():
                msg.debug('View for buf %s is not ready. Ignoring change event' % buf['id'])
                continue
            if 'patch' not in G.PERMS:
                continue
            vb_id = view.buffer_id()
            if vb_id in reported:
                continue
            if 'buf' not in buf:
                msg.debug('No data for buf %s %s yet. Skipping sending patch' % (buf['id'], buf['path']))
                continue

            reported.add(vb_id)
            patch = FlooPatch(view, buf)
            # Update the current copy of the buffer
            buf['buf'] = patch.current
            buf['md5'] = hashlib.md5(patch.current.encode('utf-8')).hexdigest()
            if Listener.agent:
                Listener.agent.put(patch.to_json())
            else:
                msg.debug('Not connected. Discarding view change.')

        while Listener.selection_changed:
            view, buf, ping = Listener.selection_changed.pop()
            # consume highlight events to avoid leak
            if 'highlight' not in G.PERMS:
                continue
            vb_id = view.buffer_id()
            if vb_id in reported:
                continue

            reported.add(vb_id)
            sel = view.sel()
            highlight_json = {
                'id': buf['id'],
                'name': 'highlight',
                'ranges': [[x.a, x.b] for x in sel],
                'ping': ping,
            }
            if Listener.agent:
                Listener.agent.put(highlight_json)
            else:
                msg.debug('Not connected. Discarding selection change.')

        sublime.set_timeout(Listener.push, 100)

    @staticmethod
    def apply_patch(patch_data):
        buf_id = patch_data['id']
        buf = BUFS[buf_id]
        view = get_view(buf_id)
        DMP = dmp.diff_match_patch()
        if len(patch_data['patch']) == 0:
            msg.error('wtf? no patches to apply. server is being stupid')
            return
        msg.debug('patch is', patch_data['patch'])
        dmp_patches = DMP.patch_fromText(patch_data['patch'])
        # TODO: run this in a separate thread
        if view:
            old_text = get_text(view)
        else:
            old_text = buf.get('buf', '')
        md5_before = hashlib.md5(old_text.encode('utf-8')).hexdigest()
        if md5_before != patch_data['md5_before']:
            msg.warn('starting md5s don\'t match for %s. this is dangerous!' % buf['path'])

        t = DMP.patch_apply(dmp_patches, old_text)

        clean_patch = True
        for applied_patch in t[1]:
            if not applied_patch:
                clean_patch = False
                break

        if G.DEBUG:
            if len(t[0]) == 0:
                msg.debug('OMG EMPTY!')
                msg.debug('Starting data:', buf['buf'])
                msg.debug('Patch:', patch_data['patch'])
            if '\x01' in t[0]:
                msg.debug('FOUND CRAZY BYTE IN BUFFER')
                msg.debug('Starting data:', buf['buf'])
                msg.debug('Patch:', patch_data['patch'])

        if not clean_patch:
            msg.error('failed to patch %s cleanly. re-fetching buffer' % buf['path'])
            return Listener.get_buf(buf_id)

        cur_hash = hashlib.md5(t[0].encode('utf-8')).hexdigest()
        if cur_hash != patch_data['md5_after']:
            msg.warn(
                '%s new hash %s != expected %s. re-fetching buffer...' %
                (buf['path'], cur_hash, patch_data['md5_after'])
            )
            return Listener.get_buf(buf_id)

        buf['buf'] = t[0]
        buf['md5'] = cur_hash

        if not view:
            save_buf(buf)
            return

        selections = [x for x in view.sel()]  # deep copy
        regions = []
        for patch in t[2]:
            offset = patch[0]
            length = patch[1]
            patch_text = patch[2]
            region = sublime.Region(offset, offset + length)
            regions.append(region)
            MODIFIED_EVENTS.put(1)
            try:
                view.run_command('floo_view_replace_region', {'r': (offset, offset + length), 'data': patch_text})
            except:
                raise
            else:
                new_sels = []
                for sel in selections:
                    a = sel.a
                    b = sel.b
                    new_offset = len(patch_text) - length
                    if sel.a > offset:
                        a += new_offset
                    if sel.b > offset:
                        b += new_offset
                    new_sels.append(sublime.Region(a, b))
                selections = [x for x in new_sels]

        view.sel().clear()
        region_key = 'floobits-patch-' + patch_data['username']
        view.add_regions(region_key, regions, 'floobits.patch', 'circle', sublime.DRAW_OUTLINED)
        sublime.set_timeout(lambda: view.erase_regions(region_key), 1000)
        for sel in selections:
            SELECTED_EVENTS.put(1)
            view.sel().add(sel)

        now = datetime.now()
        view.set_status('Floobits', 'Changed by %s at %s' % (patch_data['username'], now.strftime('%H:%M')))

    @staticmethod
    def get_buf(buf_id):
        req = {
            'name': 'get_buf',
            'id': buf_id
        }
        Listener.agent.put(req)

    @staticmethod
    def create_buf(path):
        # >>> (lambda x: lambda: x)(2)()
        # TODO: check if functools can do this in st2
        #  really_create_buf = lambda x: (lambda: Listener.create_buf(x))
        def really_create_buf(x):
            return (lambda: Listener.create_buf(x))
        if not utils.is_shared(path):
            msg.error('Skipping adding %s because it is not in shared path %s.' % (path, G.PROJECT_PATH))
            return
        if os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                # Don't care about hidden stuff
                dirnames[:] = [d for d in dirnames if d[0] != '.']
                for f in filenames:
                    f_path = os.path.join(dirpath, f)
                    if f[0] == '.':
                        msg.log('Not creating buf for hidden file %s' % f_path)
                    else:
                        sublime.set_timeout(really_create_buf(f_path), 0)
            return
        try:
            buf_fd = open(path, 'rb')
            buf = buf_fd.read().decode('utf-8')
            rel_path = utils.to_rel_path(path)
            msg.log('creating buffer ', rel_path)
            event = {
                'name': 'create_buf',
                'buf': buf,
                'path': rel_path,
            }
            Listener.agent.put(event)
        except (IOError, OSError):
            msg.error('Failed to open %s.' % path)
        except Exception as e:
            msg.error('Failed to create buffer %s: %s' % (path, str(e)))

    @staticmethod
    def delete_buf(path):
        if not utils.is_shared(path):
            msg.error('Skipping deleting %s because it is not in shared path %s.' % (path, G.PROJECT_PATH))
            return
        if os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                # Don't care about hidden stuff
                dirnames[:] = [d for d in dirnames if d[0] != '.']
                for f in filenames:
                    f_path = os.path.join(dirpath, f)
                    if f[0] == '.':
                        msg.log('Not deleting buf for hidden file %s' % f_path)
                    else:
                        Listener.delete_buf(f_path)
            return
        buf_to_delete = None
        rel_path = utils.to_rel_path(path)
        for buf_id, buf in BUFS.items():
            if rel_path == buf['path']:
                buf_to_delete = buf
                break
        if buf_to_delete is None:
            msg.error('%s is not in this room' % path)
            return
        msg.log('deleting buffer ', rel_path)
        event = {
            'name': 'delete_buf',
            'id': buf_to_delete['id'],
        }
        Listener.agent.put(event)

    @staticmethod
    def update_view(buf, view=None):
        view = view or get_view(buf['id'])
        visible_region = view.visible_region()
        viewport_position = view.viewport_position()
        # deep copy
        selections = [x for x in view.sel()]
        MODIFIED_EVENTS.put(1)
        try:
            view.run_command('floo_view_replace_region', {'r': (0, view.size()), 'data': buf['buf']})
        except Exception as e:
            msg.error('Exception updating view: %s' % e)
        sublime.set_timeout(lambda: view.set_viewport_position(viewport_position, False), 0)
        view.sel().clear()
        view.show(visible_region, False)
        for sel in selections:
            view.sel().add(sel)
        if 'patch' in G.PERMS:
            view.set_read_only(False)
        else:
            view.set_status('Floobits', 'You don\'t have write permission. Buffer is read-only.')
            view.set_read_only(True)

    @staticmethod
    def highlight(buf_id, region_key, username, ranges, ping=False):
        if G.FOLLOW_MODE:
            ping = True
        buf = BUFS.get(buf_id)
        if not buf:
            return
        view = get_view(buf_id)
        if not view:
            if ping:
                view = create_view(buf)
            return
            # TODO: scroll to highlight if we just created the view
        regions = []
        for r in ranges:
            regions.append(sublime.Region(*r))
        view.erase_regions(region_key)
        view.add_regions(region_key, regions, region_key, 'dot', sublime.DRAW_OUTLINED)
        if ping:
            G.ROOM_WINDOW.focus_view(view)
            view.show_at_center(regions[0])

    def id(self, view):
        return view.buffer_id()

    def name(self, view):
        return view.file_name()

    def on_new(self, view):
        msg.debug('new', self.name(view))

    def on_clone(self, view):
        msg.debug('clone', self.name(view))

    def on_close(self, view):
        msg.debug('close', self.name(view))
        if G.CHAT_VIEW and view.file_name() == G.CHAT_VIEW.file_name():
            G.CHAT_VIEW = None

    def on_load(self, view):
        msg.debug('load', self.name(view))

    def on_pre_save(self, view):
        p = view.name()
        if view.file_name():
            p = utils.to_rel_path(view.file_name())
        self.between_save_events[view.buffer_id()] = p

    def on_post_save(self, view):
        def cleanup():
            del self.between_save_events[view.buffer_id()]
        if view == G.CHAT_VIEW or view.file_name() == G.CHAT_VIEW_PATH:
            return cleanup()
        else:
            print(G.CHAT_VIEW_PATH, "not", view.file_name())
        event = None
        buf = get_buf(view)
        name = utils.to_rel_path(view.file_name())
        old_name = self.between_save_events[view.buffer_id()]

        if buf is None:
            if utils.is_shared(view.file_name()):
                msg.log('new buffer ', name, view.file_name())
                event = {
                    'name': 'create_buf',
                    'buf': get_text(view),
                    'path': name
                }
        elif name != old_name:
            if utils.is_shared(view.file_name()):
                msg.log('renamed buffer {0} to {1}'.format(old_name, name))
                event = {
                    'name': 'rename_buf',
                    'id': buf['id'],
                    'path': name
                }
            else:
                msg.log('deleting buffer from shared: {0}'.format(name))
                event = {
                    'name': 'delete_buf',
                    'id': buf['id'],
                }

        if event and Listener.agent:
            Listener.agent.put(event)

        cleanup()

    def on_modified(self, view):
        try:
            MODIFIED_EVENTS.get_nowait()
        except queue.Empty:
            self.add(view)
        else:
            MODIFIED_EVENTS.task_done()

    def on_selection_modified(self, view):
        try:
            SELECTED_EVENTS.get_nowait()
        except queue.Empty:
            buf = get_buf(view)
            if buf:
                msg.debug('selection in view %s, buf id %s' % (buf['path'], buf['id']))
                self.selection_changed.append((view, buf, False))
        else:
            SELECTED_EVENTS.task_done()

    @staticmethod
    def ping(view):
        buf = get_buf(view)
        if buf:
            msg.debug('pinging selection in view %s, buf id %s' % (buf['path'], buf['id']))
            Listener.selection_changed.append((view, buf, True))

    def on_activated(self, view):
        self.add(view)

    def add(self, view):
        buf = get_buf(view)
        if buf:
            msg.debug('changed view %s buf id %s' % (buf['path'], buf['id']))
            self.views_changed.append((view, buf))

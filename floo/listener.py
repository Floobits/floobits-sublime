import Queue
import json
import hashlib
import collections
from datetime import datetime

import sublime
import sublime_plugin
import dmp_monkey
dmp_monkey.monkey_patch()
from lib import diff_match_patch as dmp

import shared as G
import utils

MODIFIED_EVENTS = Queue.Queue()
BUF_STATE = collections.defaultdict(str)
BUF_IDS_TO_VIEWS = {}

settings = sublime.load_settings('Floobits.sublime-settings')


def get_text(view):
    return view.substr(sublime.Region(0, view.size()))


def get_or_create_view(buf_id, path):
    view = BUF_IDS_TO_VIEWS.get(buf_id)
    if not view:
        view = G.ROOM_WINDOW.open_file(path)
        BUF_IDS_TO_VIEWS[buf_id] = view
        print('Created view', view.name() or view.file_name())
    return view


def vbid_to_buf_id(vb_id):
    for buf_id, view in BUF_IDS_TO_VIEWS.iteritems():
        if view.buffer_id() == vb_id:
            return buf_id
    return None


class FlooPatch(object):

    def __init__(self, view):
        self.buf_id = None
        self.vb_id = view.buffer_id()
        # to rel path
        self.path = utils.to_rel_path(view.file_name())
        self.current = get_text(view)
        self.previous = BUF_STATE[self.vb_id]
        self.md5_before = hashlib.md5(self.previous).hexdigest()
        self.buf_id = vbid_to_buf_id(self.vb_id)

    def __str__(self):
        return '%s - %s - %s' % (self.buf_id, self.path, self.vb_id)

    def patches(self):
        return dmp.diff_match_patch().patch_make(self.previous, self.current)

    def to_json(self):
        patches = self.patches()
        if len(patches) == 0:
            return None
        print('sending %s patches' % len(patches))
        patch_str = ''
        for patch in patches:
            patch_str += str(patch)
        return json.dumps({
            'id': str(self.buf_id),
            'md5_after': hashlib.md5(self.current).hexdigest(),
            'md5_before': self.md5_before,
            'path': self.path,
            'patch': patch_str,
            'name': 'patch'
        })


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
            view = Listener.views_changed.pop()

            vb_id = view.buffer_id()
            if vb_id in reported:
                continue

            reported.add(vb_id)
            patch = FlooPatch(view)
            # update the current copy of the buffer
            BUF_STATE[vb_id] = patch.current
            if Listener.agent:
                Listener.agent.put(patch.to_json())
            else:
                print('Not connected. Discarding view change.')

        while Listener.selection_changed:
            view = Listener.selection_changed.pop()
            if view.is_scratch():
                continue
            vb_id = view.buffer_id()
            if vb_id in reported:
                continue

            reported.add(vb_id)
            sel = view.sel()
            buf_id = vbid_to_buf_id(vb_id)
            if buf_id is None:
                # print('buf_id for view not found. Not sending highlight.')
                continue
            highlight_json = json.dumps({
                'id': buf_id,
                'name': 'highlight',
                'ranges': [[x.a, x.b] for x in sel]
            })
            if Listener.agent:
                Listener.agent.put(highlight_json)
            else:
                print('Not connected. Discarding selection change.')

        sublime.set_timeout(Listener.push, 100)

    @staticmethod
    def apply_patch(patch_data):
        buf_id = patch_data['id']
        path = utils.get_full_path(patch_data['path'])
        view = get_or_create_view(buf_id, path)

        DMP = dmp.diff_match_patch()
        if len(patch_data['patch']) == 0:
            print('no patches to apply')
            return
        print('patch is', patch_data['patch'])
        dmp_patches = DMP.patch_fromText(patch_data['patch'])
        # TODO: run this in a separate thread
        old_text = get_text(view)
        md5_before = hashlib.md5(old_text).hexdigest()
        if md5_before != patch_data['md5_before']:
            print("starting md5s don't match. this is dangerous!")

        t = DMP.patch_apply(dmp_patches, old_text)

        clean_patch = True
        for applied_patch in t[1]:
            if not applied_patch:
                clean_patch = False
                break

        if not clean_patch:
            print('failed to patch')
            return Listener.get_buf(buf_id)

        cur_hash = hashlib.md5(t[0]).hexdigest()
        if cur_hash != patch_data['md5_after']:
            print('new hash %s != expected %s' % (cur_hash, patch_data['md5_after']))
            # TODO: do something better than erasing local changes
            return Listener.get_buf(buf_id)

        selections = [x for x in view.sel()]  # deep copy
        # so we don't send a patch back to the server for this
        BUF_STATE[view.buffer_id()] = str(t[0]).decode('utf-8')
        regions = []
        for patch in t[2]:
            offset = patch[0]
            length = patch[1]
            patch_text = patch[2]
            region = sublime.Region(offset, offset + length)
            regions.append(region)
            # print(region)
            # print('replacing', view.substr(region), 'with', patch_text.decode('utf-8'))
            MODIFIED_EVENTS.put(1)
            try:
                edit = view.begin_edit()
                view.replace(edit, region, patch_text.decode('utf-8'))
            finally:
                view.end_edit(edit)
        view.sel().clear()
        region_key = 'floobits-patch-' + patch_data['username']
        view.add_regions(region_key, regions, 'floobits.patch', 'circle', sublime.DRAW_OUTLINED)
        sublime.set_timeout(lambda: view.erase_regions(region_key), 1000)
        for sel in selections:
            # print('re-adding selection', sel)
            view.sel().add(sel)

        now = datetime.now()
        view.set_status('Floobits', 'Changed by %s at %s' % (patch_data['username'], now.strftime('%H:%M')))

    @staticmethod
    def get_buf(buf_id):
        req = {
            'name': 'get_buf',
            'id': buf_id
        }
        Listener.agent.put(json.dumps(req))

    @staticmethod
    def update_buf(buf_id, path, text, md5, view=None, save=False):
        path = utils.get_full_path(path)
        view = get_or_create_view(buf_id, path)
        visible_region = view.visible_region()
        viewport_position = view.viewport_position()
        region = sublime.Region(0, view.size())
        selections = [x for x in view.sel()]  # deep copy
        MODIFIED_EVENTS.put(1)
        # so we don't send a patch back to the server for this
        BUF_STATE[view.buffer_id()] = text.decode('utf-8')
        try:
            edit = view.begin_edit()
            view.replace(edit, region, text.decode('utf-8'))
        except Exception as e:
            print('Exception updating view:', e)
        finally:
            view.end_edit(edit)
        sublime.set_timeout(lambda: view.set_viewport_position(viewport_position, False), 0)
        view.sel().clear()
        view.show(visible_region, False)
        for sel in selections:
            # print('re-adding selection', sel)
            view.sel().add(sel)
        view.set_read_only(G.READ_ONLY)
        if G.READ_ONLY:
            view.set_status('Floobits', "You don't have write permission. Buffer is read-only.")

        # print('view text is now %s' % get_text(view))
        if save:
            view.run_command("save")

    @staticmethod
    def highlight(buf_id, region_key, username, ranges):
        view = BUF_IDS_TO_VIEWS.get(buf_id)
        if not view:
            # print('No view for buffer id', buf_id)
            return
        regions = []
        for r in ranges:
            regions.append(sublime.Region(*r))
        view.erase_regions(region_key)
        view.add_regions(region_key, regions, region_key, 'dot', sublime.DRAW_OUTLINED)

    def id(self, view):
        return view.buffer_id()

    def name(self, view):
        return view.file_name()

    def on_new(self, view):
        print('new', self.name(view))

    def on_clone(self, view):
        print('clone', self.name(view))

    def on_load(self, view):
        print('load', self.name(view))

    def on_pre_save(self, view):
        p = view.name()
        if view.file_name():
            p = utils.to_rel_path(view.file_name())
        self.between_save_events[view.buffer_id()] = p

    def on_post_save(self, view):
        event = None
        buf_id = vbid_to_buf_id(view.buffer_id())
        name = utils.to_rel_path(view.file_name())
        old_name = self.between_save_events[view.buffer_id()]

        if buf_id is None:
            if utils.is_shared(view.file_name()):
                print('new buffer', name, view.file_name())
                event = {
                    'name': 'create_buf',
                    'buf': get_text(view),
                    'path': name
                }
        elif name != old_name:
            if utils.is_shared(view.file_name()):
                print('renamed buffer {0} to {1}'.format(old_name, name))
                event = {
                    'name': 'rename_buf',
                    'id': buf_id,
                    'path': name
                }
            else:
                print('deleting buffer from shared: {0}'.format(name))
                event = {
                    'name': 'delete_buf',
                    'id': buf_id,
                }

        if event and Listener.agent:
            Listener.agent.put(json.dumps(event))

        del self.between_save_events[view.buffer_id()]

    def on_modified(self, view):
        if not settings.get('run', True):
            return
        try:
            MODIFIED_EVENTS.get_nowait()
        except Queue.Empty:
            self.add(view)
        else:
            MODIFIED_EVENTS.task_done()

    def on_selection_modified(self, view):
        if not settings.get('run', True):
            return
        self.selection_changed.append(view)

    def on_activated(self, view):
        if view.is_scratch():
            return
        self.add(view)

    def add(self, view):
        vb_id = view.buffer_id()
        # This could probably be more efficient
        for buf_id, v in BUF_IDS_TO_VIEWS.iteritems():
            if v.buffer_id() == vb_id:
                print('view is in BUF_IDS_TO_VIEWS. sending patch')
                self.views_changed.append(view)
                break
        if view.is_scratch():
            print('is scratch')
            return

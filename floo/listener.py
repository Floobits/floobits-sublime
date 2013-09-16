try:
    unicode()
except NameError:
    unicode = str

import os
import hashlib
from datetime import datetime
import base64
import stat
import collections

import sublime
import sublime_plugin

try:
    from .common import ignore, msg, shared as G, utils
    from .common.lib import DMP
    assert DMP and ignore and G and msg and utils
except ImportError:
    from common import ignore, msg, shared as G, utils
    from common.lib import DMP


BUFS = {}
CREATE_BUF_CBS = {}
PATHS_TO_IDS = {}
ON_LOAD = {}
disable_stalker_mode_timeout = None
temp_disable_stalk = False
MAX_FILE_SIZE = 1024 * 1024 * 5


def get_text(view):
    return view.substr(sublime.Region(0, view.size()))


def get_view(buf_id):
    buf = BUFS.get(buf_id)
    if buf is None:
        return None
    for view in G.WORKSPACE_WINDOW.views():
        if not view.file_name():
            continue
        if buf['path'] == utils.to_rel_path(view.file_name()):
            return view
    return None


def create_view(buf):
    path = utils.get_full_path(buf['path'])
    view = G.WORKSPACE_WINDOW.open_file(path)
    if view:
        msg.debug('Created view', view.name() or view.file_name())
    return view


def get_buf_by_path(path):
    p = utils.to_rel_path(path)
    buf_id = PATHS_TO_IDS.get(p)
    if buf_id:
        return BUFS.get(buf_id)


def get_buf(view):
    if view.is_scratch():
        return None
    if not view.file_name():
        return None
    if view is G.CHAT_VIEW:
        return None
    return get_buf_by_path(view.file_name())


def is_view_loaded(view):
    """returns a buf if the view is loaded in sublime and
    the buf is populated by us"""

    if not G.JOINED_WORKSPACE or view.is_loading():
        return

    buf = get_buf(view)
    if not buf or buf.get('buf') is None:
        return

    return buf


def save_buf(buf):
    path = utils.get_full_path(buf['path'])
    utils.mkdir(os.path.split(path)[0])
    with open(path, 'wb') as fd:
        if buf['encoding'] == 'utf8':
            fd.write(buf['buf'].encode('utf-8'))
        else:
            fd.write(buf['buf'])


def delete_buf(buf_id):
    # TODO: somehow tell the user about this
    view = get_view(buf_id)
    try:
        if view:
            view.set_scratch(True)
            G.WORKSPACE_WINDOW.focus_view(view)
            G.WORKSPACE_WINDOW.run_command("close_file")
    except Exception as e:
        msg.debug('Error closing view: %s' % unicode(e))
    try:
        buf = BUFS.get(buf_id)
        if buf:
            del PATHS_TO_IDS[buf['path']]
            del BUFS[buf_id]
    except KeyError:
        msg.debug('KeyError deleting buf id %s' % buf_id)


def reenable_stalker_mode():
    global disable_stalker_mode_timeout, temp_disable_stalk
    temp_disable_stalk = False
    disable_stalker_mode_timeout = None


def disable_stalker_mode(timeout):
    global disable_stalker_mode_timeout, temp_disable_stalk
    if G.STALKER_MODE is True:
        temp_disable_stalk = True
        disable_stalker_mode_timeout = utils.set_timeout(reenable_stalker_mode, timeout)
    elif disable_stalker_mode_timeout:
        utils.cancel_timeout(disable_stalker_mode_timeout)
        disable_stalker_mode_timeout = utils.set_timeout(reenable_stalker_mode, timeout)


def send_summon(buf_id, sel):
    highlight_json = {
        'id': buf_id,
        'name': 'highlight',
        'ranges': sel,
        'ping': True,
        'summon': True,
    }
    if G.AGENT and G.AGENT.is_ready():
        G.AGENT.put(highlight_json)


class CreationQueue(object):
    def __init__(self):
        self.dirs = []
        self.files = []


class Listener(sublime_plugin.EventListener):
    views_changed = []
    selection_changed = []
    creation_deque = collections.deque()

    def __init__(self, *args, **kwargs):
        sublime_plugin.EventListener.__init__(self, *args, **kwargs)
        self.between_save_events = {}

    @staticmethod
    def reset():
        global BUFS, CREATE_BUF_CBS, PATHS_TO_IDS
        BUFS = {}
        CREATE_BUF_CBS = {}
        PATHS_TO_IDS = {}
        Listener.views_changed = []
        Listener.selection_changed = []
        Listener.creation_deque = collections.deque()

    @staticmethod
    def push():
        reported = set()
        while Listener.views_changed:
            view, buf = Listener.views_changed.pop()
            if not G.JOINED_WORKSPACE:
                msg.debug('Not connected. Discarding view change.')
                continue
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
            patch = utils.FlooPatch(get_text(view), buf)
            # Update the current copy of the buffer
            buf['buf'] = patch.current
            buf['md5'] = hashlib.md5(patch.current.encode('utf-8')).hexdigest()
            G.AGENT.put(patch.to_json())

        reported = set()
        while Listener.selection_changed:
            view, buf, summon = Listener.selection_changed.pop()

            if not G.JOINED_WORKSPACE:
                msg.debug('Not connected. Discarding selection change.')
                continue
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
                'ping': summon,
                'summon': summon,
            }
            G.AGENT.put(highlight_json)

    @staticmethod
    def apply_patch(patch_data):
        if not G.AGENT:
            msg.debug('Not connected. Discarding view change.')
            return
        buf_id = patch_data['id']
        buf = BUFS[buf_id]
        if 'buf' not in buf:
            msg.debug('buf %s not populated yet. not patching' % buf['path'])
            return
        if buf['encoding'] == 'base64':
            # TODO apply binary patches
            return Listener.get_buf(buf_id, None)

        view = get_view(buf_id)
        if len(patch_data['patch']) == 0:
            msg.error('wtf? no patches to apply. server is being stupid')
            return
        msg.debug('patch is', patch_data['patch'])
        dmp_patches = DMP.patch_fromText(patch_data['patch'])
        # TODO: run this in a separate thread
        old_text = buf['buf']

        if view and not view.is_loading():
            view_text = get_text(view)
            if old_text == view_text:
                buf['forced_patch'] = False
            elif not buf.get('forced_patch'):
                patch = utils.FlooPatch(get_text(view), buf)
                # Update the current copy of the buffer
                buf['buf'] = patch.current
                buf['md5'] = hashlib.md5(patch.current.encode('utf-8')).hexdigest()
                buf['forced_patch'] = True
                msg.debug('forcing patch for %s' % buf['path'])
                G.AGENT.put(patch.to_json())
                old_text = view_text
            else:
                msg.debug('forced patch is true. not sending another patch for buf %s' % buf['path'])
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
                try:
                    msg.debug('OMG EMPTY!')
                    msg.debug('Starting data:', buf['buf'])
                    msg.debug('Patch:', patch_data['patch'])
                except Exception as e:
                    print(e)

            if '\x01' in t[0]:
                msg.debug('FOUND CRAZY BYTE IN BUFFER')
                msg.debug('Starting data:', buf['buf'])
                msg.debug('Patch:', patch_data['patch'])

        timeout_id = buf.get('timeout_id')
        if timeout_id:
            utils.cancel_timeout(timeout_id)

        if not clean_patch:
            msg.log('Couldn\'t patch %s cleanly.' % buf['path'])
            return Listener.get_buf(buf_id, view)

        cur_hash = hashlib.md5(t[0].encode('utf-8')).hexdigest()
        if cur_hash != patch_data['md5_after']:
            buf['timeout_id'] = utils.set_timeout(Listener.get_buf, 2000, buf_id, view)

        buf['buf'] = t[0]
        buf['md5'] = cur_hash

        if not view:
            save_buf(buf)
            return

        regions = []
        commands = []
        for patch in t[2]:
            offset = patch[0]
            length = patch[1]
            patch_text = patch[2]
            region = sublime.Region(offset, offset + length)
            regions.append(region)
            commands.append({'r': [offset, offset + length], 'data': patch_text})

        view.run_command('floo_view_replace_regions', {'commands': commands})
        region_key = 'floobits-patch-' + patch_data['username']
        view.add_regions(region_key, regions, 'floobits.patch', 'circle', sublime.DRAW_OUTLINED)
        utils.set_timeout(view.erase_regions, 2000, region_key)

        view.set_status('Floobits', 'Changed by %s at %s' % (patch_data['username'], datetime.now().strftime('%H:%M')))

    @staticmethod
    def get_buf(buf_id, view=None):
        req = {
            'name': 'get_buf',
            'id': buf_id
        }
        buf = BUFS[buf_id]
        msg.warn('Syncing buffer %s for consistency.' % buf['path'])
        if 'buf' in buf:
            del buf['buf']
        if view:
            view.set_read_only(True)
            view.set_status('Floobits', 'Floobits locked this file until it is synced.')
        G.AGENT.put(req)

    @staticmethod
    def create_buf(path, ig=None):
        if not ig:
            ig = ignore.Ignore(None, path)
        ignores = collections.deque([ig])
        files = collections.deque()
        Listener._create_buf_worker(ignores, files, [])

    @staticmethod
    def _create_buf_worker(ignores, files, too_big):
        quota = 10

        # scan until we find a minimum of 10 files
        while quota > 0 and ignores:
            ig = ignores.popleft()
            for new_path in Listener._scan_dir(ig):
                if not new_path:
                    continue
                try:
                    s = os.lstat(new_path)
                except Exception as e:
                    msg.error('Error lstat()ing path %s: %s' % (new_path, unicode(e)))
                    continue
                if stat.S_ISDIR(s.st_mode):
                    ignores.append(ignore.Ignore(ig, new_path))
                elif stat.S_ISREG(s.st_mode):
                    if s.st_size > (MAX_FILE_SIZE):
                        too_big.append(new_path)
                    else:
                        files.append(new_path)
                    quota -= 1

        can_upload = False
        for f in utils.iter_n_deque(files, 10):
            Listener.upload(f)
            can_upload = True

        if can_upload and G.AGENT and G.AGENT.sock:
            G.AGENT.select()

        if ignores or files:
            return utils.set_timeout(Listener._create_buf_worker, 25, ignores, files, too_big)

        if too_big:
            sublime.error_message("%s file(s) were not added because they were larger than 10 megabytes: \n%s" % (len(too_big), "\t".join(too_big)))

        msg.log('All done syncing')

    @staticmethod
    def _scan_dir(ig):
        path = ig.path

        if not utils.is_shared(path):
            msg.error('Skipping adding %s because it is not in shared path %s.' % (path, G.PROJECT_PATH))
            return
        ignored = ig.is_ignored(path)
        if ignored:
            msg.log('Not creating buf: %s' % (ignored))
            return

        msg.debug('create_buf: path is %s' % path)

        if not os.path.isdir(path):
            yield path
            return

        try:
            paths = os.listdir(path)
        except Exception as e:
            msg.error('Error listing path %s: %s' % (path, unicode(e)))
            return
        for p in paths:
            p_path = os.path.join(path, p)
            if p[0] == '.':
                if p not in ignore.HIDDEN_WHITELIST:
                    msg.log('Not creating buf for hidden path %s' % p_path)
                    continue
            ignored = ig.is_ignored(p_path)
            if ignored:
                msg.log('Not creating buf: %s' % (ignored))
                continue

            yield p_path

    @staticmethod
    def upload(path):
        try:
            with open(path, 'rb') as buf_fd:
                buf = buf_fd.read()
            encoding = 'utf8'
            rel_path = utils.to_rel_path(path)
            existing_buf = get_buf_by_path(path)
            if existing_buf:
                buf_md5 = hashlib.md5(buf).hexdigest()
                if existing_buf['md5'] == buf_md5:
                    msg.log('%s already exists and has the same md5. Skipping.' % path)
                    return
                msg.log('setting buffer ', rel_path)

                existing_buf['buf'] = buf
                existing_buf['md5'] = buf_md5

                try:
                    buf = buf.decode('utf-8')
                except Exception:
                    buf = base64.b64encode(buf).decode('utf-8')
                    encoding = 'base64'

                existing_buf['encoding'] = encoding

                G.AGENT.put({
                    'name': 'set_buf',
                    'id': existing_buf['id'],
                    'buf': buf,
                    'md5': buf_md5,
                    'encoding': encoding,
                })
                return

            try:
                buf = buf.decode('utf-8')
            except Exception:
                buf = base64.b64encode(buf).decode('utf-8')
                encoding = 'base64'

            msg.log('creating buffer ', rel_path)
            event = {
                'name': 'create_buf',
                'buf': buf,
                'path': rel_path,
                'encoding': encoding,
            }
            G.AGENT.put(event)
        except (IOError, OSError):
            msg.error('Failed to open %s.' % path)
        except Exception as e:
            msg.error('Failed to create buffer %s: %s' % (path, unicode(e)))

    @staticmethod
    def delete_buf(path):
        if not utils.is_shared(path):
            msg.error('Skipping deleting %s because it is not in shared path %s.' % (path, G.PROJECT_PATH))
            return
        if os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                # TODO: rexamine this assumption
                # Don't care about hidden stuff
                dirnames[:] = [d for d in dirnames if d[0] != '.']
                for f in filenames:
                    f_path = os.path.join(dirpath, f)
                    if f[0] == '.':
                        msg.log('Not deleting buf for hidden file %s' % f_path)
                    else:
                        Listener.delete_buf(f_path)
            return
        buf_to_delete = get_buf_by_path(path)
        if buf_to_delete is None:
            msg.error('%s is not in this workspace' % path)
            return
        msg.log('deleting buffer ', utils.to_rel_path(path))
        event = {
            'name': 'delete_buf',
            'id': buf_to_delete['id'],
        }
        G.AGENT.put(event)

    @staticmethod
    def update_view(buf, view):
        msg.log('Floobits synced data for consistency: %s' % buf['path'])
        G.VIEW_TO_HASH[view.buffer_id()] = buf['md5']
        view.set_read_only(False)
        try:
            view.run_command('floo_view_replace_region', {'r': [0, view.size()], 'data': buf['buf']})
            view.set_status('Floobits', 'Floobits synced data for consistency.')
            utils.set_timeout(lambda: view.set_status('Floobits', ''), 5000)
        except Exception as e:
            msg.error('Exception updating view: %s' % e)
        if 'patch' not in G.PERMS:
            view.set_status('Floobits', 'You don\'t have write permission. Buffer is read-only.')
            view.set_read_only(True)

    @staticmethod
    def highlight(buf_id, region_key, username, ranges, summon=False):
        buf = BUFS.get(buf_id)
        if not buf:
            return
        view = get_view(buf_id)
        if not view:
            if summon or (G.STALKER_MODE and not temp_disable_stalk):
                view = create_view(buf)
                ON_LOAD[buf_id] = lambda: Listener.highlight(buf_id, region_key, username, ranges, summon)
            return
        regions = []
        for r in ranges:
            regions.append(sublime.Region(*r))
        view.erase_regions(region_key)
        view.add_regions(region_key, regions, region_key, 'dot', sublime.DRAW_OUTLINED)
        if summon or (G.STALKER_MODE and not temp_disable_stalk):
            G.WORKSPACE_WINDOW.focus_view(view)
            if summon:
                # Explicit summon by another user. Center the line.
                view.show_at_center(regions[0])
            else:
                # Avoid scrolling/jumping lots in stalker mode
                view.show(regions[0])

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
        # TODO: the view was closed, but maybe another one is open that shares the buffer_id
        # if G.VIEW_TO_HASH.get(view.buffer_id()):
        #     del G.VIEW_TO_HASH[view.buffer_id()]

    def on_load(self, view):
        msg.debug('Sublime loaded %s' % self.name(view))
        buf = get_buf(view)
        if buf:
            f = ON_LOAD.get(buf['id'])
            if f:
                del ON_LOAD[buf['id']]
                f()

    def on_pre_save(self, view):
        if not G.AGENT or not G.AGENT.is_ready():
            return
        p = view.name()
        if view.file_name():
            p = utils.to_rel_path(view.file_name())
        self.between_save_events[view.buffer_id()] = p

    def on_post_save(self, view):
        if not G.AGENT or not G.AGENT.is_ready():
            return

        def cleanup():
            del self.between_save_events[view.buffer_id()]

        if view == G.CHAT_VIEW or view.file_name() == G.CHAT_VIEW_PATH:
            return cleanup()

        event = None
        buf = get_buf(view)
        name = utils.to_rel_path(view.file_name())
        is_shared = utils.is_shared(view.file_name())
        old_name = self.between_save_events[view.buffer_id()]

        if buf is None:
            if is_shared:
                msg.log('new buffer ', name, view.file_name())
                event = {
                    'name': 'create_buf',
                    'buf': get_text(view),
                    'path': name
                }
        elif name != old_name:
            if is_shared:
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

        if event:
            G.AGENT.put(event)
        if is_shared and buf:
            G.AGENT.put({'name': 'saved', 'id': buf['id']})

        cleanup()

    def on_modified(self, view):
        buf = is_view_loaded(view)
        if not buf:
            return

        text = get_text(view)
        if buf['encoding'] != 'utf8':
            return msg.warn('Floobits does not support patching binary files at this time')

        text = text.encode('utf-8')
        view_md5 = hashlib.md5(text).hexdigest()
        if view_md5 == G.VIEW_TO_HASH.get(view.buffer_id()):
            return

        G.VIEW_TO_HASH[view.buffer_id()] = view_md5

        msg.debug('changed view %s buf id %s' % (buf['path'], buf['id']))

        disable_stalker_mode(2000)
        buf['forced_patch'] = False
        self.views_changed.append((view, buf))

    def on_selection_modified(self, view, buf=None):
        buf = is_view_loaded(view)
        if buf:
            disable_stalker_mode(2000)
            self.selection_changed.append((view, buf, False))

    @staticmethod
    def clear_highlights(view):
        if not G.AGENT:
            return
        buf = get_buf(view)
        if not buf:
            return
        msg.debug('clearing highlights in %s, buf id %s' % (buf['path'], buf['id']))
        for user_id, username in G.AGENT.workspace_info['users'].items():
            view.erase_regions('floobits-highlight-%s' % user_id)

    @staticmethod
    def summon(view):
        buf = get_buf(view)
        if buf:
            msg.debug('summoning selection in view %s, buf id %s' % (buf['path'], buf['id']))
            Listener.selection_changed.append((view, buf, True))
        else:
            path = view.file_name()
            if not utils.is_shared(path):
                sublime.error_message('Can\'t summon because %s is not in shared path %s.' % (path, G.PROJECT_PATH))
                return
            share = sublime.ok_cancel_dialog('This file isn\'t shared. Would you like to share it?', 'Share')
            if share:
                sel = [[x.a, x.b] for x in view.sel()]
                CREATE_BUF_CBS[utils.to_rel_path(path)] = lambda buf_id: send_summon(buf_id, sel)
                Listener.create_buf(path)

    def on_activated(self, view):
        buf = get_buf(view)
        if buf:
            msg.debug('activated view %s buf id %s' % (buf['path'], buf['id']))
            self.on_modified(view)
            self.selection_changed.append((view, buf, False))

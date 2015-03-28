import os
import time
import hashlib
import collections

import sublime_plugin

try:
    from .common import msg, shared as G, utils
    from .sublime_utils import get_buf, get_text
    assert G and G and utils and msg and get_buf and get_text
except ImportError:
    from common import msg, shared as G, utils
    from sublime_utils import get_buf, get_text


def if_connected(f):
    def wrapped(*args):
        if not G.AGENT or not G.AGENT.is_ready():
            return
        args = list(args)
        args.append(G.AGENT)
        return f(*args)
    return wrapped


def is_view_loaded(view):
    """returns a buf if the view is loaded in sublime and
    the buf is populated by us"""

    if not G.AGENT:
        return
    if not G.AGENT.joined_workspace:
        return
    if view.is_loading():
        return

    buf = get_buf(view)
    if not buf or buf.get('buf') is None:
        return

    return buf


class Listener(sublime_plugin.EventListener):

    def __init__(self, *args, **kwargs):
        sublime_plugin.EventListener.__init__(self, *args, **kwargs)
        self._highlights = set()
        self._view_selections = {}
        self.between_save_events = collections.defaultdict(lambda: [0, ''])
        self.disable_follow_mode_timeout = None

    @if_connected
    def on_post_window_command(self, window, command, *args, **kwargs):
        agent = args[-1]
        if command == 'delete_file':
            # User probably deleted a file. Stat and delete.
            files = args[0]['files']
            for f in files:
                buf = agent.get_buf_by_path(f)
                if not buf:
                    continue
                if os.path.exists(f):
                    continue
                agent.send({
                    'name': 'delete_buf',
                    'id': buf['id'],
                })
            return

        if command == 'delete_folder':
            dirs = args[0]['dirs']
            for d in dirs:
                # Delete folder prompt just closed. Check if folder exists
                if os.path.isdir(d):
                    continue
                rel_path = utils.to_rel_path(d)
                if not rel_path:
                    msg.error('Can not delete %s from workspace', d)
                    continue
                for buf_id, buf in G.AGENT.bufs.items():
                    if buf['path'].startswith(rel_path):
                        agent.send({
                            'name': 'delete_buf',
                            'id': buf_id,
                        })

    @if_connected
    def on_window_command(self, window, command, *args, **kwargs):
        if command == 'rename_path':
            # User is about to rename something
            msg.debug('rename')
        if window == G.WORKSPACE_WINDOW and command == 'close_window':
            msg.log('Workspace window closed, disconnecting.')
            try:
                window.run_command('floobits_leave_workspace')
            except Exception as e:
                msg.error(e)

    def name(self, view):
        return view.file_name()

    def on_new(self, view):
        msg.debug('Sublime new ', self.name(view))

    @if_connected
    def reenable_follow_mode(self, agent):
        agent.temp_disable_follow = False
        self.disable_follow_mode_timeout = None

    @if_connected
    def disable_follow_mode(self, timeout, agent):
        if G.FOLLOW_MODE is True:
            agent.temp_disable_follow = True
        utils.cancel_timeout(self.disable_follow_mode_timeout)
        self.disable_follow_mode_timeout = utils.set_timeout(self.reenable_follow_mode, timeout)

    @if_connected
    def on_clone(self, view, agent):
        msg.debug('Sublime cloned ', self.name(view))
        buf = get_buf(view)
        if not buf:
            return
        buf_id = int(buf['id'])
        f = agent.on_clone.get(buf_id)
        if not f:
            return
        del agent.on_clone[buf_id]
        f(buf, view)

    @if_connected
    def on_close(self, view, agent):
        msg.debug('Sublime closed view ', self.name(view))

    @if_connected
    def on_load(self, view, agent):
        msg.debug('Sublime loaded ', self.name(view))
        buf = get_buf(view)
        if not buf:
            return
        buf_id = int(buf['id'])
        d = agent.on_load.get(buf_id)
        if not d:
            return
        del agent.on_load[buf_id]
        for _, f in d.items():
            f()

    @if_connected
    def on_pre_save(self, view, agent):
        if view.is_scratch():
            return
        p = view.name()
        if view.file_name():
            try:
                p = utils.to_rel_path(view.file_name())
            except ValueError:
                p = view.file_name()
        i = self.between_save_events[view.buffer_id()]
        i[0] += 1
        i[1] = p

    @if_connected
    def on_post_save(self, view, agent):
        view_buf_id = view.buffer_id()

        def cleanup():
            i = self.between_save_events[view_buf_id]
            i[0] -= 1

        if view.is_scratch():
            return

        i = self.between_save_events[view_buf_id]
        if agent.ignored_saves[view_buf_id] > 0:
            agent.ignored_saves[view_buf_id] -= 1
            return cleanup()
        old_name = i[1]

        i = self.between_save_events[view_buf_id]
        if i[0] > 1:
            return cleanup()
        old_name = i[1]

        event = None
        buf = get_buf(view)
        try:
            name = utils.to_rel_path(view.file_name())
        except ValueError:
            name = view.file_name()
        is_shared = utils.is_shared(view.file_name())

        if buf is None:
            if not is_shared:
                return cleanup()
            if G.IGNORE and G.IGNORE.is_ignored(view.file_name(), log=True):
                msg.log(view.file_name(), ' is ignored. Not creating buffer.')
                return cleanup()
            msg.log('Creating new buffer ', name, view.file_name())
            event = {
                'name': 'create_buf',
                'buf': get_text(view),
                'path': name
            }
        elif name != old_name:
            if is_shared:
                msg.log('renamed buffer ', old_name, ' to ', name)
                event = {
                    'name': 'rename_buf',
                    'id': buf['id'],
                    'path': name
                }
            else:
                msg.log('deleting buffer from shared: ', name)
                event = {
                    'name': 'delete_buf',
                    'id': buf['id'],
                }

        if event:
            agent.send(event)
        if is_shared and buf:
            agent.send({'name': 'saved', 'id': buf['id']})

        cleanup()

    @if_connected
    def on_modified(self, view, agent):
        buf = is_view_loaded(view)
        if not buf:
            return

        text = get_text(view)
        if buf['encoding'] != 'utf8':
            return msg.warn('Floobits does not support patching binary files at this time')

        text = text.encode('utf-8')
        view_md5 = hashlib.md5(text).hexdigest()
        bid = view.buffer_id()
        buf['forced_patch'] = False
        if view_md5 == G.VIEW_TO_HASH.get(bid):
            self._highlights.add(bid)
            return

        G.VIEW_TO_HASH[view.buffer_id()] = view_md5
        msg.debug('changed view ', buf['path'], ' buf id ', buf['id'])
        self.disable_follow_mode(2000)
        agent.views_changed.append((view, buf))

    @if_connected
    def on_selection_modified(self, view, agent, buf=None):
        buf = is_view_loaded(view)
        if not buf or 'highlight' not in G.PERMS:
            return
        c = [[x.a, x.b] for x in view.sel()]
        bid = view.buffer_id()
        previous = self._view_selections.get(bid, {})
        now = time.time()
        if previous.get("sel") == c:
            t = previous.get("time", 0)
            if now - t < 1:
                return

        previous['time'] = now
        previous['sel'] = c
        self._view_selections[bid] = previous

        discard = bid in self._highlights
        if discard:
            self._highlights.discard(bid)
        if agent.joined_workspace:
            agent.send({
                'id': buf['id'],
                'name': 'highlight',
                'ranges': c,
                'ping': False,
                'summon': False,
                'following': discard,
            })

    @if_connected
    def on_activated(self, view, agent):
        buf = get_buf(view)
        if buf:
            msg.debug('activated view ', buf['path'], ' buf id ', buf['id'])
            self.on_modified(view)
            self.on_selection_modified(view)

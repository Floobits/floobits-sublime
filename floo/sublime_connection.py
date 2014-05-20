import os
import hashlib
import sublime
import collections

try:
    import ssl
    assert ssl
except ImportError:
    ssl = False

try:
    unicode()
except NameError:
    unicode = str

try:
    from . import editor
    from .common import msg, shared as G, utils
    from .view import View
    from .common.handlers import floo_handler
    from .sublime_utils import create_view, get_buf, send_summon, get_view_in_group
    assert G and msg and utils
except ImportError:
    from floo import editor
    from common import msg, shared as G, utils
    from common.handlers import floo_handler
    from view import View
    from sublime_utils import create_view, get_buf, send_summon, get_view_in_group


class SublimeConnection(floo_handler.FlooHandler):

    def tick(self):
        reported = set()
        while self.views_changed:
            v, buf = self.views_changed.pop()
            if not self.joined_workspace:
                msg.debug('Not connected. Discarding view change.')
                continue
            if 'patch' not in G.PERMS:
                continue
            if 'buf' not in buf:
                msg.debug('No data for buf %s %s yet. Skipping sending patch' % (buf['id'], buf['path']))
                continue
            view = View(v, buf)
            if view.is_loading():
                msg.debug('View for buf %s is not ready. Ignoring change event' % buf['id'])
                continue
            if view.native_id in reported:
                continue
            reported.add(view.native_id)
            patch = utils.FlooPatch(view.get_text(), buf)
            # Update the current copy of the buffer
            buf['buf'] = patch.current
            buf['md5'] = hashlib.md5(patch.current.encode('utf-8')).hexdigest()
            self.send(patch.to_json())

        reported = set()
        while self.selection_changed:
            v, buf, summon = self.selection_changed.pop()

            if not self.joined_workspace:
                msg.debug('Not connected. Discarding selection change.')
                continue
            # consume highlight events to avoid leak
            if 'highlight' not in G.PERMS:
                continue

            view = View(v, buf)
            vb_id = view.native_id
            if vb_id in reported:
                continue

            reported.add(vb_id)
            highlight_json = {
                'id': buf['id'],
                'name': 'highlight',
                'ranges': view.get_selections(),
                'ping': summon,
                'summon': summon,
                'following': G.STALKER_MODE,
            }
            self.send(highlight_json)

        self._status_timeout += 1
        if self._status_timeout > (2000 / G.TICK_TIME):
            self.update_status_msg()

    def update_status_msg(self, status=''):
        self._status_timeout = 0
        if G.STALKER_MODE:
            status += 'Following changes in'
        else:
            status += 'Connected to'
        status += ' %s/%s as %s' % (self.owner, self.workspace, self.username)
        editor.status_message(status)

    def stomp_prompt(self, changed_bufs, missing_bufs, cb):
        if not G.EXPERT_MODE:
            editor.message_dialog('Your copy of %s/%s is out of sync. '
                                  'You will be prompted after you close this dialog.' % (self.owner, self.workspace))

        def pluralize(arg):
            return len(arg) > 1 and 's' or ''

        diffs = changed_bufs + missing_bufs
        overwrite_local = ''
        overwrite_remote = ''

        if changed_bufs:
            if len(diffs) < 5:
                changed = ', '.join([buf['path'] for buf in changed_bufs])
            else:
                changed = len(changed_bufs)
            overwrite_local += 'Fetch %s' % changed
            overwrite_remote += 'Upload %s' % changed

            if missing_bufs:
                if len(diffs) < 5:
                    missing = ', '.join([buf['path'] for buf in missing_bufs])
                else:
                    missing = '%s remote file%s.' % (len(missing_bufs), pluralize(missing_bufs))
                overwrite_local += ' and fetch %s' % missing
                overwrite_remote += ' and remove %s' % missing
            elif len(diffs) >= 5:
                overwrite_remote += ' file%s.' % pluralize(changed_bufs)
                overwrite_local += ' remote file%s.' % pluralize(changed_bufs)
        elif missing_bufs:
            if len(diffs) < 5:
                missing = ', '.join([buf['path'] for buf in missing_bufs])
            else:
                missing = '%s remote file%s.' % (len(missing_bufs), pluralize(missing_bufs))
            overwrite_local += 'Fetch %s.' % missing
            overwrite_remote += 'Remove %s.' % missing

        opts = [
            ['Overwrite %s remote file%s' % (len(diffs), pluralize(diffs)), overwrite_remote],
            ['Overwrite %s local file%s' % (len(diffs), pluralize(diffs)), overwrite_local],
            ['Cancel', 'Disconnect and resolve conflict manually.'],
        ]
        # TODO: sublime text doesn't let us focus a window. so use the active window. super lame
        # G.WORKSPACE_WINDOW.show_quick_panel(opts, cb)
        w = sublime.active_window() or G.WORKSPACE_WINDOW
        w.show_quick_panel(opts, cb)

    def ok_cancel_dialog(self, msg, cb=None):
        res = sublime.ok_cancel_dialog(msg)
        return (cb and cb(res) or res)

    def error_message(self, msg):
        sublime.error_message(msg)

    def status_message(self, msg):
        sublime.status_message(msg)

    def get_view(self, buf_id):
        buf = self.bufs.get(buf_id)
        if not buf:
            return

        for v in G.WORKSPACE_WINDOW.views():
            if not v.file_name():
                continue
            try:
                rel_path = utils.to_rel_path(v.file_name())
            except ValueError:
                continue
            if buf['path'] == rel_path:
                return View(v, buf)

    def save_view(self, view):
        self.ignored_saves[view.native_id] += 1
        view.save()

    def reset(self):
        super(self.__class__, self).reset()
        self.on_clone = {}
        self.create_buf_cbs = {}
        self.temp_disable_stalk = False
        self.temp_ignore_highlight = {}
        self.temp_ignore_highlight = {}
        self.views_changed = []
        self.selection_changed = []
        self.ignored_saves = collections.defaultdict(int)
        self._status_timeout = 0
        self.last_highlight = None

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
        msg.MSG(data.get('data'), data['time'], data['username']).display()

    def get_username_by_id(self, user_id):
        try:
            return self.workspace_info['users'][str(user_id)]['username']
        except Exception:
            return ''

    def delete_buf(self, path, unlink=False):
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
                        self.delete_buf(f_path, unlink)
            return
        buf_to_delete = self.get_buf_by_path(path)
        if buf_to_delete is None:
            msg.error('%s is not in this workspace' % path)
            return
        msg.log('deleting buffer ', utils.to_rel_path(path))
        event = {
            'name': 'delete_buf',
            'id': buf_to_delete['id'],
            'unlink': unlink,
        }
        self.send(event)

    def highlight(self, data=None):
        data = data or self.last_highlight
        if not data:
            msg.log('No recent highlight to replay.')
            return
        self._on_highlight(data)

    def _on_highlight(self, data, clone=True):
        self.last_highlight = data
        region_key = 'floobits-highlight-%s' % (data['user_id'])
        buf_id = int(data['id'])
        username = data['username']
        ranges = data['ranges']
        summon = data.get('ping', False)
        msg.debug(str([buf_id, region_key, username, ranges, summon, clone]))
        buf = self.bufs.get(buf_id)
        if not buf:
            return

        # TODO: move this state machine into one variable
        b = self.on_load.get(buf_id)
        if b and b.get('highlight'):
            msg.debug('ignoring command until on_load is complete')
            return
        if buf_id in self.on_clone:
            msg.debug('ignoring command until on_clone is complete')
            return
        if buf_id in self.temp_ignore_highlight:
            msg.debug('ignoring command until temp_ignore_highlight is complete')
            return

        if G.STALKER_MODE:
            if self.temp_disable_stalk or data.get('following'):
                do_stuff = False
            else:
                do_stuff = True
        else:
            do_stuff = summon

        view = self.get_view(buf_id)
        if not view or view.is_loading():
            if do_stuff:
                msg.debug('creating view')
                create_view(buf)
                self.on_load[buf_id]['highlight'] = lambda: self._on_highlight(data, False)
            return
        view = view.view
        regions = []
        for r in ranges:
            regions.append(sublime.Region(*r))

        def swap_regions(v):
            v.erase_regions(region_key)
            v.add_regions(region_key, regions, region_key, 'dot', sublime.DRAW_OUTLINED)

        if not do_stuff:
            return swap_regions(view)

        win = G.WORKSPACE_WINDOW

        if not G.SPLIT_MODE:
            win.focus_view(view)
            swap_regions(view)
            # Explicit summon by another user. Center the line.
            if summon:
                view.show_at_center(regions[0])
            # Avoid scrolling/jumping lots in stalker mode
            else:
                view.show(regions[0])
            return

        focus_group = win.num_groups() - 1
        view_in_group = get_view_in_group(view.buffer_id(), focus_group)

        if view_in_group:
            msg.debug('view in group')
            win.focus_view(view_in_group)
            swap_regions(view_in_group)
            utils.set_timeout(win.focus_group, 0, 0)
            return view_in_group.show(regions[0])

        if not clone:
            msg.debug('no clone... moving ', view.buffer_id(), win.num_groups() - 1, 0)
            win.focus_view(view)
            win.set_view_index(view, win.num_groups() - 1, 0)

            def dont_crash_sublime():
                utils.set_timeout(win.focus_group, 0, 0)
                swap_regions(view)
                return view.show(regions[0])
            return utils.set_timeout(dont_crash_sublime, 0)

        msg.debug('View not in group... cloning')
        win.focus_view(view)

        def on_clone(buf, view):
            msg.debug('on clone')

            def poll_for_move():
                msg.debug('poll_for_move')
                win.focus_view(view)
                win.set_view_index(view, win.num_groups() - 1, 0)
                if not get_view_in_group(view.buffer_id(), focus_group):
                    return utils.set_timeout(poll_for_move, 20)
                msg.debug('found view, now moving ', view.name(), win.num_groups() - 1)
                swap_regions(view)
                view.show(regions[0])
                win.focus_view(view)
                utils.set_timeout(win.focus_group, 0, 0)
                try:
                    del self.temp_ignore_highlight[buf_id]
                except Exception:
                    pass
            utils.set_timeout(win.focus_group, 0, 0)
            poll_for_move()

        self.on_clone[buf_id] = on_clone
        self.temp_ignore_highlight[buf_id] = True
        win.run_command('clone_file')
        return win.focus_group(0)

    def clear_highlights(self, view):
        buf = get_buf(view)
        if not buf:
            return
        msg.debug('clearing highlights in %s, buf id %s' % (buf['path'], buf['id']))
        for user_id, username in self.workspace_info['users'].items():
            view.erase_regions('floobits-highlight-%s' % user_id)

    def summon(self, view):
        buf = get_buf(view)
        if buf:
            msg.debug('summoning selection in view %s, buf id %s' % (buf['path'], buf['id']))
            self.selection_changed.append((view, buf, True))
        else:
            path = view.file_name()
            if not utils.is_shared(path):
                sublime.error_message('Can\'t summon because %s is not in shared path %s.' % (path, G.PROJECT_PATH))
                return
            share = sublime.ok_cancel_dialog('This file isn\'t shared. Would you like to share it?', 'Share')
            if share:
                sel = [[x.a, x.b] for x in view.sel()]
                self.create_buf_cbs[utils.to_rel_path(path)] = lambda buf_id: send_summon(buf_id, sel)
                self.upload(path)

    def _on_delete_buf(self, data):
        # TODO: somehow tell the user about this
        view = self.get_view(data['id'])
        if view:
            try:
                view = view.view
                view.set_scratch(True)
                G.WORKSPACE_WINDOW.focus_view(view)
                G.WORKSPACE_WINDOW.run_command("close_file")
            except Exception as e:
                msg.debug('Error closing view: %s' % unicode(e))
        super(self.__class__, self)._on_delete_buf(data)

    def _on_create_buf(self, data):
        super(self.__class__, self)._on_create_buf(data)
        cb = self.create_buf_cbs.get(data['path'])
        if not cb:
            return
        del self.create_buf_cbs[data['path']]
        try:
            cb(data['id'])
        except Exception as e:
            print(e)

    def _on_part(self, data):
        super(self.__class__, self)._on_part(data)
        region_key = 'floobits-highlight-%s' % (str(data['user_id']))
        for window in sublime.windows():
            for view in window.views():
                view.erase_regions(region_key)

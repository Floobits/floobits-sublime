import os
import sublime
import collections

try:
    import ssl
    assert ssl
except ImportError:
    ssl = False

try:
    from . import editor
    from .common import msg, shared as G, utils
    from .common.exc_fmt import str_e
    from .view import View
    from .common.handlers import floo_handler
    from .sublime_utils import create_view, get_buf, send_summon, get_view_in_group, get_text
    assert G and msg and utils
except ImportError:
    from floo import editor
    from common import msg, shared as G, utils
    from common.exc_fmt import str_e
    from common.handlers import floo_handler
    from view import View
    from sublime_utils import create_view, get_buf, send_summon, get_view_in_group, get_text


class SublimeConnection(floo_handler.FlooHandler):
    def __init__(self, owner, workspace, context, auth, action):
        super(SublimeConnection, self).__init__(owner, workspace, auth, action)
        self.context = context
        self.on('room_info', self.log_users)

    def tick(self):
        if 'patch' not in G.PERMS:
            self.views_changed = []
        elif not self.joined_workspace:
            msg.debug('Not connected. Discarding view change.')
            self.views_changed = []
        else:
            reported = set()
            to_send = []
            while self.views_changed:
                name, v, buf = self.views_changed.pop()
                if 'buf' not in buf:
                    msg.debug('No data for buf ', buf['id'], ' ', buf['path'], ' yet. Skipping sending patch')
                    continue
                view = View(v, buf)
                if view.is_loading():
                    msg.debug('View for buf ', buf['id'], ' is not ready. Ignoring change event.')
                    continue
                if view.native_id in reported:
                    continue
                reported.add((name, view.native_id))
                if name == 'patch':
                    patch = utils.FlooPatch(view.get_text(), buf)
                    # Update the current copy of the buffer
                    buf['buf'] = patch.current
                    buf['md5'] = patch.md5_after
                    self.send(patch.to_json())
                    continue
                if name == 'saved':
                    to_send.append({'name': 'saved', 'id': buf['id']})
                    continue
                msg.warn('Discarding unknown event in views_changed:', name)

            for s in to_send:
                self.send(s)

        self._status_timeout += 1
        if self._status_timeout > (2000 / G.TICK_TIME):
            self.update_status_msg()

    def update_status_msg(self, status=''):
        self._status_timeout = 0
        if G.FOLLOW_MODE:
            if G.FOLLOW_USERS:
                status += 'Following '
                for username in G.FOLLOW_USERS:
                    status += '%s' % (username)
                status += ' in'
            else:
                status += 'Following changes in'
        elif self.joined_workspace:
            status += 'Connected to'
        else:
            status += 'Connecting to'
        status += ' %s/%s as %s' % (self.owner, self.workspace, self.username)
        editor.status_message(status)

    def log_users(self):
        clients = []
        try:
            clients = ['%s on %s' % (x.get('username'), x.get('client')) for x in self.workspace_info['users'].values()]
        except Exception as e:
            print(e)
        msg.log(len(clients), ' connected clients:')
        clients.sort()
        for client in clients:
            msg.log(client)

    def show_connections_list(self, users, cb):
        opts = [[user, ''] for user in users]
        w = sublime.active_window() or G.WORKSPACE_WINDOW
        w.show_quick_panel(opts, cb)

    def stomp_prompt(self, changed_bufs, missing_bufs, new_files, ignored, cb):
        if not (G.EXPERT_MODE or hasattr(sublime, 'KEEP_OPEN_ON_FOCUS_LOST')):
            editor.message_dialog('Your copy of %s/%s is out of sync. '
                                  'You will be prompted after you close this dialog.' % (self.owner, self.workspace))

        def pluralize(arg):
            return arg != 1 and 's' or ''

        overwrite_local = ''
        overwrite_remote = ''
        missing = [buf['path'] for buf in missing_bufs]
        changed = [buf['path'] for buf in changed_bufs]

        to_remove = set(missing + ignored)
        to_upload = set(new_files + changed).difference(to_remove)
        to_fetch = changed + missing
        to_upload_len = len(to_upload)
        to_remove_len = len(to_remove)
        remote_len = to_remove_len + to_upload_len
        to_fetch_len = len(to_fetch)

        msg.log('To fetch: ', ', '.join(to_fetch))
        msg.log('To upload: ', ', '.join(to_upload))
        msg.log('To remove: ', ', '.join(to_remove))

        if not to_fetch:
            overwrite_local = 'Fetch nothing'
        elif to_fetch_len < 5:
            overwrite_local = 'Fetch %s' % ', '.join(to_fetch)
        else:
            overwrite_local = 'Fetch %s file%s' % (to_fetch_len, pluralize(to_fetch_len))

        if to_upload_len < 5:
            to_upload_str = 'Upload %s' % ', '.join(to_upload)
        else:
            to_upload_str = 'Upload %s' % to_upload_len

        if to_remove_len < 5:
            to_remove_str = 'remove %s' % ', '.join(to_remove)
        else:
            to_remove_str = 'remove %s' % to_remove_len

        if to_upload:
            overwrite_remote += to_upload_str
            if to_remove:
                overwrite_remote += ' and '
        if to_remove:
            overwrite_remote += to_remove_str

        if remote_len >= 5 and overwrite_remote:
            overwrite_remote += ' files'

        # Be fancy and capitalize "remove" if it's the first thing in the string
        if len(overwrite_remote) > 0:
            overwrite_remote = overwrite_remote[0].upper() + overwrite_remote[1:]

        connected_users_msg = ''

        def filter_user(u):
            if u.get('is_anon'):
                return False
            if 'patch' not in u.get('perms'):
                return False
            if u.get('username') == self.username:
                return False
            return True

        users = set([v['username'] for k, v in self.workspace_info['users'].items() if filter_user(v)])
        if users:
            if len(users) < 4:
                connected_users_msg = ' Connected: ' + ','.join(users)
            else:
                connected_users_msg = ' %s users connected' % len(users)

        # TODO: change action based on numbers of stuff
        action = 'Overwrite'
        opts = [
            ['%s %s remote file%s.' % (action, remote_len, pluralize(remote_len)), overwrite_remote],
            ['%s %s local file%s.' % (action, to_fetch_len, pluralize(to_fetch_len)), overwrite_local],
            ['Cancel', 'Disconnect.' + connected_users_msg],
        ]

        w = sublime.active_window() or G.WORKSPACE_WINDOW
        flags = 0
        if hasattr(sublime, 'KEEP_OPEN_ON_FOCUS_LOST'):
            flags |= sublime.KEEP_OPEN_ON_FOCUS_LOST
        w.show_quick_panel(opts, cb, flags)

    def ok_cancel_dialog(self, msg, cb=None):
        res = sublime.ok_cancel_dialog(msg)
        return (cb and cb(res) or res)

    def error_message(self, msg):
        sublime.error_message(msg)

    def status_message(self, msg):
        sublime.status_message(msg)

    def get_view_text_by_path(self, path):
        for v in G.WORKSPACE_WINDOW.views():
            if not v.file_name():
                continue
            try:
                rel_path = utils.to_rel_path(v.file_name())
            except ValueError:
                continue
            if path == rel_path:
                return get_text(v)

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
        self.temp_disable_follow = False
        self.temp_ignore_highlight = {}
        self.temp_ignore_highlight = {}
        self.views_changed = []
        self.ignored_saves = collections.defaultdict(int)
        self._status_timeout = 0
        self.last_highlight = None
        self.last_highlight_by_user = {}

    def prompt_join_hangout(self, hangout_url):
        hangout_client = None
        users = self.workspace_info.get('users')
        for user_id, user in users.items():
            if user['username'] == self.username and 'hangout' in user['client']:
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
            msg.error('Skipping deleting ', path, ' because it is not in shared path ', G.PROJECT_PATH, '.')
            return
        if os.path.isdir(path):
            for dirpath, dirnames, filenames in os.walk(path):
                # TODO: rexamine this assumption
                # Don't care about hidden stuff
                dirnames[:] = [d for d in dirnames if d[0] != '.']
                for f in filenames:
                    f_path = os.path.join(dirpath, f)
                    if f[0] == '.':
                        msg.log('Not deleting buf for hidden file ', f_path)
                    else:
                        self.delete_buf(f_path, unlink)
            return
        buf_to_delete = self.get_buf_by_path(path)
        if buf_to_delete is None:
            msg.error(path, ' is not in this workspace')
            return
        msg.log('deleting buffer ', utils.to_rel_path(path))
        event = {
            'name': 'delete_buf',
            'id': buf_to_delete['id'],
            'unlink': unlink,
        }
        self.send(event)

    def highlight(self, data=None, user=None):
        if user:
            data = self.last_highlight_by_user.get(user)
        elif not data:
            data = data or self.last_highlight

        if not data:
            msg.log('No recent highlight to replay.')
            return

        self._on_highlight(data)

    def _on_highlight(self, data, clone=True):
        region_key = 'floobits-highlight-%s' % (data['user_id'])
        buf_id = int(data['id'])
        username = data['username']
        ranges = data['ranges']
        summon = data.get('ping', False)
        user_id = str(data['user_id'])
        msg.debug(str([buf_id, region_key, user_id, username, ranges, summon, data.get('following'), clone]))
        if not ranges:
            msg.warn('Ignoring empty highlight from', username)
            return
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

        if summon or not data.get('following'):
            self.last_highlight = data
            self.last_highlight_by_user[username] = data

        do_stuff = summon
        if G.FOLLOW_MODE and not summon:
            if self.temp_disable_follow or data.get('following'):
                do_stuff = False
            elif G.FOLLOW_USERS:
                do_stuff = username in G.FOLLOW_USERS
            else:
                do_stuff = True

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
            # TODO: add one to the ranges that have a length of zero
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
            # Avoid scrolling/jumping lots in follow mode
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
        msg.debug('clearing highlights in ', buf['path'], ', buf id ', buf['id'])
        for user_id, username in self.workspace_info['users'].items():
            view.erase_regions('floobits-highlight-%s' % user_id)

    def summon(self, subl_view):
        if 'highlight' not in G.PERMS:
            return
        buf = get_buf(subl_view)
        if buf:
            msg.debug('summoning selection in subl_view ', buf['path'], ', buf id ', buf['id'])
            c = [[x.a, x.b] for x in subl_view.sel()]
            if self.joined_workspace:
                self.send({
                    'id': buf['id'],
                    'name': 'highlight',
                    'ranges': c,
                    'ping': True,
                    'summon': True,
                    'following': False,
                })
            return

        path = subl_view.file_name()
        if not utils.is_shared(path):
            sublime.error_message('Can\'t summon because %s is not in shared path %s.' % (path, G.PROJECT_PATH))
            return
        share = sublime.ok_cancel_dialog('This file isn\'t shared. Would you like to share it?', 'Share')
        if share:
            sel = [[x.a, x.b] for x in subl_view.sel()]
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
                msg.debug('Error closing view: ', str_e(e))
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
            print(str_e(e))

    def _on_part(self, data):
        super(self.__class__, self)._on_part(data)
        region_key = 'floobits-highlight-%s' % (str(data['user_id']))
        for window in sublime.windows():
            for view in window.views():
                view.erase_regions(region_key)

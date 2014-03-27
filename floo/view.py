from datetime import datetime

import sublime

try:
    from .common import msg, shared as G, utils
    from .sublime_utils import get_text
    assert utils
except (ImportError, ValueError):
    from common import msg, shared as G, utils
    from sublime_utils import get_text


class View(object):
    """editors representation of the buffer"""

    def __init__(self, view, buf):
        self.view = view
        self.buf = buf

    def __repr__(self):
        return '%s %s %s' % (self.native_id, self.buf['id'], self.buf['path'].encode('utf-8'))

    def __str__(self):
        return repr(self)

    @property
    def native_id(self):
        return self.view.buffer_id()

    def is_loading(self):
        return self.view.is_loading()

    def get_text(self):
        return get_text(self.view)

    def apply_patches(self, buf, patches, username):
        regions = []
        commands = []
        for patch in patches[2]:
            offset = patch[0]
            length = patch[1]
            patch_text = patch[2]
            region = sublime.Region(offset, offset + length)
            regions.append(region)
            commands.append({'r': [offset, offset + length], 'data': patch_text})

        self.view.run_command('floo_view_replace_regions', {'commands': commands})
        region_key = 'floobits-patch-' + username
        self.view.add_regions(region_key, regions, 'floobits.patch', 'circle', sublime.DRAW_OUTLINED)
        utils.set_timeout(self.view.erase_regions, 2000, region_key)
        self.set_status('Changed by %s at %s' % (username, datetime.now().strftime('%H:%M')))

    def update(self, buf, message=True):
        self.buf = buf
        if message:
            msg.log('Floobits synced data for consistency: %s' % buf['path'])
        G.VIEW_TO_HASH[self.view.buffer_id()] = buf['md5']
        self.view.set_read_only(False)
        try:
            self.view.run_command('floo_view_replace_region', {'r': [0, self.view.size()], 'data': buf['buf']})
            if message:
                self.set_status('Floobits synced data for consistency.')
            utils.set_timeout(self.set_status, 5000, '')
        except Exception as e:
            msg.error('Exception updating view: %s' % e)
        if 'patch' not in G.PERMS:
            self.set_status('You don\'t have write permission. Buffer is read-only.')
            self.view.set_read_only(True)

    def set_status(self, status):
        self.view.set_status('Floobits', status)

    def set_read_only(self, ro):
        self.view.set_read_only(ro)

    def focus(self):
        raise NotImplemented()

    def set_cursor_position(self, offset):
        raise NotImplemented()

    def get_cursor_position(self):
        raise NotImplemented()

    def get_cursor_offset(self):
        raise NotImplemented()

    def get_selections(self):
        return [[x.a, x.b] for x in self.view.sel()]

    def clear_highlight(self, user_id):
        raise NotImplemented()

    def highlight(self, ranges, user_id):
        msg.debug('highlighting ranges %s' % (ranges))
        raise NotImplemented()

    def rename(self, name):
        self.view.retarget(name)

    def save(self):
        if 'buf' in self.buf:
            self.view.run_command('save')
        else:
            msg.debug("not saving because not populated")

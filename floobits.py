# coding: utf-8
import sys
import os
import hashlib
import subprocess
import threading

import sublime_plugin
import sublime

PY2 = sys.version_info < (3, 0)

if PY2 and sublime.platform() == 'windows':
    err_msg = '''Sorry, but the Windows version of Sublime Text 2 lacks Python's select module, so the Floobits plugin won't work.
Please upgrade to Sublime Text 3. :('''
    raise(Exception(err_msg))
elif sublime.platform() == 'osx':
    try:
        p = subprocess.Popen(['/usr/bin/sw_vers', '-productVersion'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = p.communicate()
        if float(result[0][:4]) < 10.7:
            sublime.error_message('''Sorry, but the Floobits plugin doesn\'t work on 10.6 or earlier.
Please upgrade your operating system if you want to use this plugin. :(''')
    except Exception as e:
        print(e)

try:
    from .floo import version
    from .floo import sublime_utils as sutils
    from .floo.listener import Listener
    from .floo.common import reactor, shared as G, utils
    from .floo.common.exc_fmt import str_e
    assert utils
except (ImportError, ValueError):
    from floo import version
    from floo import sublime_utils as sutils
    from floo.listener import Listener
    from floo.common import reactor, shared as G, utils
    from floo.common.exc_fmt import str_e

reactor = reactor.reactor

from window_commands import FloobitsOpenSettingsCommand, FloobitsShareDirCommand, FloobitsCreateWorkspaceCommand, \
    FloobitsPromptJoinWorkspaceCommand, FloobitsJoinWorkspaceCommand, FloobitsPinocchioCommand, \
    FloobitsLeaveWorkspaceCommand, FloobitsClearHighlightsCommand, FloobitsSummonCommand, \
    FloobitsJoinRecentWorkspaceCommand, FloobitsAddToWorkspaceCommand, FloobitsRemoveFromWorkspaceCommand, \
    FloobitsCreateHangoutCommand, FloobitsPromptHangoutCommand, FloobitsOpenWebEditorCommand, FloobitsHelpCommand, \
    FloobitsToggleStalkerModeCommand, FloobitsEnableStalkerModeCommand, FloobitsDisableStalkerModeCommand, \
    FloobitsOpenWorkspaceSettingsCommand, RequestPermissionCommand, FloobitsFollowSplit, FloobitsNotACommand, \
    create_or_link_account

assert Listener and version and FloobitsOpenSettingsCommand and FloobitsShareDirCommand and FloobitsCreateWorkspaceCommand and \
    FloobitsPromptJoinWorkspaceCommand and FloobitsJoinWorkspaceCommand and FloobitsPinocchioCommand and \
    FloobitsLeaveWorkspaceCommand and FloobitsClearHighlightsCommand and FloobitsSummonCommand and \
    FloobitsJoinRecentWorkspaceCommand and FloobitsAddToWorkspaceCommand and FloobitsRemoveFromWorkspaceCommand and \
    FloobitsCreateHangoutCommand and FloobitsPromptHangoutCommand and FloobitsOpenWebEditorCommand and FloobitsHelpCommand and \
    FloobitsToggleStalkerModeCommand and FloobitsEnableStalkerModeCommand and FloobitsDisableStalkerModeCommand and \
    FloobitsOpenWorkspaceSettingsCommand and RequestPermissionCommand and FloobitsFollowSplit and FloobitsNotACommand


ignore_modified_timeout = None


def ssl_error_msg(action):
    sublime.error_message('Your version of Sublime Text can\'t ' + action + ' because it has a broken SSL module. '
                          'This is a known issue on Linux builds of Sublime Text. '
                          'See this issue: https://github.com/SublimeText/Issues/issues/177')


def get_active_window(cb):
    win = sublime.active_window()
    if not win:
        return utils.set_timeout(get_active_window, 50, cb)
    cb(win)


def global_tick():
    # XXX: A couple of sublime 2 users have had reactor == None here
    reactor.tick()
    utils.set_timeout(global_tick, G.TICK_TIME)


def unignore_modified_events():
    G.IGNORE_MODIFIED_EVENTS = False


def transform_selections(selections, start, new_offset):
    new_sels = []
    for sel in selections:
        a = sel.a
        b = sel.b
        if sel.a > start:
            a += new_offset
        if sel.b > start:
            b += new_offset
        new_sels.append(sublime.Region(a, b))
    return new_sels


# The new ST3 plugin API sucks
class FlooViewReplaceRegion(sublime_plugin.TextCommand):
    def run(self, edit, *args, **kwargs):
        selections = [x for x in self.view.sel()]  # deep copy
        selections = self._run(edit, selections, *args, **kwargs)
        self.view.sel().clear()
        for sel in selections:
            self.view.sel().add(sel)

    def _run(self, edit, selections, r, data, view=None):
        global ignore_modified_timeout

        if not hasattr(self, 'view'):
            return selections

        G.IGNORE_MODIFIED_EVENTS = True
        utils.cancel_timeout(ignore_modified_timeout)
        ignore_modified_timeout = utils.set_timeout(unignore_modified_events, 2)
        start = max(int(r[0]), 0)
        stop = min(int(r[1]), self.view.size())
        region = sublime.Region(start, stop)

        if stop - start > 10000:
            self.view.replace(edit, region, data)
            G.VIEW_TO_HASH[self.view.buffer_id()] = hashlib.md5(sutils.get_text(self.view).encode('utf-8')).hexdigest()
            return transform_selections(selections, stop, 0)

        existing = self.view.substr(region)
        i = 0
        data_len = len(data)
        existing_len = len(existing)
        length = min(data_len, existing_len)
        while (i < length):
            if existing[i] != data[i]:
                break
            i += 1
        j = 0
        while j < (length - i):
            if existing[existing_len - j - 1] != data[data_len - j - 1]:
                break
            j += 1
        region = sublime.Region(start + i, stop - j)
        replace_str = data[i:data_len - j]
        self.view.replace(edit, region, replace_str)
        G.VIEW_TO_HASH[self.view.buffer_id()] = hashlib.md5(sutils.get_text(self.view).encode('utf-8')).hexdigest()
        new_offset = len(replace_str) - ((stop - j) - (start + i))
        return transform_selections(selections, start + i, new_offset)

    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    def description(self):
        return


# The new ST3 plugin API sucks
class FlooViewReplaceRegions(FlooViewReplaceRegion):
    def run(self, edit, commands):
        is_read_only = self.view.is_read_only()
        self.view.set_read_only(False)
        selections = [x for x in self.view.sel()]  # deep copy
        for command in commands:
            selections = self._run(edit, selections, **command)

        self.view.set_read_only(is_read_only)
        self.view.sel().clear()
        for sel in selections:
            self.view.sel().add(sel)

    def is_visible(self):
        return False

    def is_enabled(self):
        return True

    def description(self):
        return


called_plugin_loaded = False


# Sublime 3 calls this once the plugin API is ready
def plugin_loaded():
    global called_plugin_loaded
    if called_plugin_loaded:
        return
    called_plugin_loaded = True
    print('Floobits: Called plugin_loaded.')

    utils.reload_settings()

    # TODO: one day this can be removed (once all our users have updated)
    old_colab_dir = os.path.realpath(os.path.expanduser(os.path.join('~', '.floobits')))
    if os.path.isdir(old_colab_dir) and not os.path.exists(G.BASE_DIR):
        print('renaming %s to %s' % (old_colab_dir, G.BASE_DIR))
        os.rename(old_colab_dir, G.BASE_DIR)
        os.symlink(G.BASE_DIR, old_colab_dir)

    try:
        utils.normalize_persistent_data()
    except Exception as e:
        print('Floobits: Error normalizing persistent data:', str_e(e))
        # Keep on truckin' I guess

    d = utils.get_persistent_data()
    G.AUTO_GENERATED_ACCOUNT = d.get('auto_generated_account', False)

    can_auth = (G.USERNAME or G.API_KEY) and G.SECRET
    # Sublime plugin API stuff can't be called right off the bat
    if not can_auth:
        utils.set_timeout(create_or_link_account, 1)

    utils.set_timeout(global_tick, 1)

# Sublime 2 has no way to know when plugin API is ready. Horrible hack here.
if PY2:
    for i in range(0, 20):
        threading.Timer(i, utils.set_timeout, [plugin_loaded, 1]).start()

    def warning():
        if not called_plugin_loaded:
            print('Your computer is slow and could not start the Floobits reactor.  Please contact us or upgrade to Sublime Text 3.')
    threading.Timer(20, warning).start()

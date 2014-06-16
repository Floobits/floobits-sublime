import sys
import os.path
import subprocess

import sublime

try:
    from .sublime_connection import SublimeConnection
    from .common import msg, shared as G, utils, flooui
    from .common.exc_fmt import str_e
    assert G and G and utils and msg
except ImportError:
    from sublime_connection import SublimeConnection
    from common.exc_fmt import str_e
    from common import msg, shared as G, utils, flooui


PY2 = sys.version_info < (3, 0)


def get_workspace_window(abs_path):
    workspace_window = None
    for w in sublime.windows():
        for f in w.folders():
            if utils.unfuck_path(f) == utils.unfuck_path(abs_path):
                workspace_window = w
                break
    return workspace_window


def open_workspace_window2(abs_path, cb):
    if sublime.platform() == 'linux':
        subl = open('/proc/self/cmdline').read().split(chr(0))[0]
    elif sublime.platform() == 'osx':
        floorc = utils.load_floorc_json()
        subl = floorc.get('SUBLIME_EXECUTABLE')
        if not subl:
            settings = sublime.load_settings('Floobits.sublime-settings')
            subl = settings.get('sublime_executable', '/Applications/Sublime Text 2.app/Contents/SharedSupport/bin/subl')
        if not os.path.exists(subl):
            return sublime.error_message('''Can't find your Sublime Text executable at %s.
Please add "sublime_executable": "/path/to/subl" to your ~/.floorc.json and restart Sublime Text''' % subl)
    elif sublime.platform() == 'windows':
        subl = sys.executable
    else:
        raise Exception('WHAT PLATFORM ARE WE ON?!?!?')

    command = [subl]
    if get_workspace_window(abs_path) is None:
        command.append('--new-window')
    command.append('--add')
    command.append(G.PROJECT_PATH)

    msg.debug('command:', command)
    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    poll_result = p.poll()
    msg.debug('poll:', poll_result)
    cb()


def open_workspace_window3(abs_path, cb):
    def finish(w):
        w.set_project_data({'folders': [{'path': abs_path}]})
        cb(w)

    def get_empty_window():
        for w in sublime.windows():
            project_data = w.project_data()
            try:
                folders = project_data.get('folders', [])
                if len(folders) == 0 or not folders[0].get('path'):
                    # no project data. co-opt this window
                    return w
            except Exception as e:
                print(str_e(e))

    def wait_empty_window(i):
        if i > 10:
            print('Too many failures trying to find an empty window. Using active window.')
            return finish(sublime.active_window())
        w = get_empty_window()
        if w:
            return finish(w)
        return utils.set_timeout(wait_empty_window, 50, i + 1)

    w = get_workspace_window(abs_path) or get_empty_window()
    if w:
        return finish(w)

    sublime.run_command('new_window')
    wait_empty_window(0)


class SublimeUI(flooui.FlooUI):
    def _make_agent(self, owner, workspace, auth, created_workspace, d):
        """@returns new Agent()"""
        return SublimeConnection(owner, workspace, auth, created_workspace and d)

    def user_y_or_n(self, context, prompt, affirmation_txt, cb):
        """@returns True/False"""
        return cb(bool(sublime.ok_cancel_dialog(prompt, affirmation_txt)))

    def user_select(self, context, prompt, choices_big, choices_small, cb):
        """@returns (choice, index)"""
        context.show_quick_panel(choices_big, lambda i: i < 0 and cb(None, -1) or cb(choices_big[i], i))

    def user_charfield(self, context, prompt, initial, cb):
        """@returns String"""
        context.show_input_panel(prompt, initial, cb, None, None)

    @utils.inlined_callbacks
    def get_a_window(self, abs_path, cb):
        """opens a project in a window or something"""
        if PY2:
            yield open_workspace_window2, abs_path
        else:
            yield open_workspace_window3, abs_path

        while True:
            workspace_window = get_workspace_window(abs_path)
            if workspace_window is not None:
                break
            yield lambda cb: utils.set_timeout(cb, 50)
        cb(workspace_window)

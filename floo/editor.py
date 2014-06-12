import sys
import os

try:
    import sublime
except Exception:
    pass


NEW_ACCOUNT_TXT = 'Welcome {username}!\n\nYou\'re all set to collaborate. You should check out our docs at https://{host}/help/plugins/sublime#usage. \
You must run \'Floobits - Complete Sign Up\' so you can log in to the website.'

LINKED_ACCOUNT_TXT = """Welcome {username}!\n\nYou are all set to collaborate.

You may want to check out our docs at https://{host}/help/plugins/sublime#usage"""


def name():
    if sys.version_info < (3, 0):
        py_version = 2
    else:
        py_version = 3
    return 'Sublime Text %s' % py_version


def codename():
    return 'sublime'


def ok_cancel_dialog(dialog):
    return sublime.ok_cancel_dialog(dialog)


def error_message(msg):
    sublime.error_message(msg)


def status_message(msg):
    sublime.status_message(msg)


def platform():
    return sublime.platform()


def set_timeout(f, timeout):
    sublime.set_timeout(f, timeout)


def call_timeouts():
    return


def message_dialog(msg):
    sublime.message_dialog(msg)


def open_file(file):
    win = sublime.active_window()
    if win:
        win.open_file(file)


def get_line_endings(path=None):
    ending = sublime.load_settings('Preferences.sublime-settings').get('default_line_ending')
    if ending == 'system':
        return os.linesep
    if ending == 'windows':
        return '\r\n'
    return '\n'


def select_auth(*args):
    window, auths, cb = args

    if not auths:
        return cb(None)

    auths = dict(auths)
    for k, v in auths.items():
        v['host'] = k

    if len(auths) == 1:
        return cb(list(auths.values())[0])

    opts = [[h, 'Connect as %s' % a.get('username')] for h, a in auths.items()]
    opts.append(['Cancel', ''])

    def on_account(index):
        if index < 0 or index >= len(auths):
            # len(hosts) is cancel, appended to opts at end below
            return cb(None)
        host = opts[index][0]
        return cb(auths[host])

    return window.show_quick_panel(opts, on_account)

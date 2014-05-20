import sys
import os

try:
    import sublime
except Exception:
    pass

welcome_text = 'Welcome %s!\n\nYou\'re all set to collaborate. You should check out our docs at https://%s/help/plugins/sublime#usage. \
You must run \'Floobits - Complete Sign Up\' in the command palette before you can sign in to floobits.com.'


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


def select_account(*args):
    window, hosts, host, cb = args

    if len(hosts) == 1 and host and host == hosts[0]:
        return cb(hosts[0])

    if len(hosts):
        def on_account(index):
            if index == -1 or index == len(hosts):
                # len(hosts) is cancel, appended to opts at end below
                return cb(None)
            hosts.reverse()
            return cb(hosts[index])
        #  TODO: add usernames to dialog
        opts = [[h, "Use %s account." % h] for h in hosts]
        opts.reverse()
        opts.append(['Cancel'])
        return window.show_quick_panel(opts, on_account)
    return cb(None)

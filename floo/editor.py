import sublime


def ok_cancel_dialog(dialog):
    return sublime.ok_cancel_dialog(dialog)


def error_message(msg):
    sublime.error_message(msg)


def status_message(msg):
    sublime.status_message(msg)


def platform():
    return sublime.platform()


def set_timeout(*args):
    sublime.set_timeout(*args)


def open_file(file):
    win = sublime.active_window()
    if win:
        win.open_file(file)

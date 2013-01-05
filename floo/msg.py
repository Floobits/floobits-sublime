import time

import sublime

import shared as G
import utils

LOG_LEVELS = {
    'DEBUG': 1,
    'MSG': 2,
    'WARN': 3,
    'ERROR': 4,
}

LOG_LEVEL = LOG_LEVELS['MSG']


def get_or_create_chat():
    p = utils.get_full_path('msgs.floobits.log')
    if not G.ROOM_WINDOW:
        w = sublime.active_window()
        if w:
            G.ROOM_WINDOW = w
        else:
            w = sublime.windows()
            if w:
                G.ROOM_WINDOW = w[0]
            else:
                sublime.error_message('Sublime is stupid, I can\'t make a new view')
                return

    chat_view = None
    if G.CHAT_VIEW:
        for view in G.ROOM_WINDOW.views():
            if G.CHAT_VIEW.file_name() == view.file_name():
                chat_view = view
                G.CHAT_VIEW = view
                break
    if not chat_view:
        G.CHAT_VIEW = G.ROOM_WINDOW.open_file(p)
        G.CHAT_VIEW_PATH = G.CHAT_VIEW.file_name()
        G.CHAT_VIEW.set_read_only(True)
    return G.CHAT_VIEW


class MSG(object):
    def __init__(self, msg, timestamp=None, username=None, level=LOG_LEVELS['MSG']):
        self.msg = msg
        self.timestamp = timestamp or time.time()
        self.username = username
        self.level = level

    def display(self):
        if self.level < LOG_LEVEL:
            return

        def _get_or_create_chat():
            view = get_or_create_chat()
            sublime.set_timeout(lambda: _display(view), 0)

        def _display(view):
            with utils.edit(view) as ed:
                size = view.size()
                view.set_read_only(False)
                view.insert(ed, size, str(self))
                view.set_read_only(True)
                # TODO: this scrolling is lame and centers text :/
                view.show(size)

        sublime.set_timeout(_get_or_create_chat, 0)

    def __str__(self):
        if self.username:
            msg = '[{time}] <{user}> {msg}\n'
        else:
            msg = '[{time}] {msg}\n'
        return msg.format(user=self.username, time=time.ctime(self.timestamp), msg=self.msg)


def msg_format(message, *args, **kwargs):
    message += ' '.join([str(x) for x in args])
    if kwargs:
        message = message.format(**kwargs)
    return message


def _log(message, level, *args, **kwargs):
    MSG(msg_format(message, *args, **kwargs), level=level).display()


# TODO: use introspection?
def debug(message, *args, **kwargs):
    _log(message, LOG_LEVELS['DEBUG'], *args, **kwargs)


def log(message, *args, **kwargs):
    _log(message, LOG_LEVELS['MSG'], *args, **kwargs)


def warn(message, *args, **kwargs):
    _log(message, LOG_LEVELS['WARN'], *args, **kwargs)


def error(message, *args, **kwargs):
    _log(message, LOG_LEVELS['ERROR'], *args, **kwargs)

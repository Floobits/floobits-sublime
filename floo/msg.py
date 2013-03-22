import os
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


def get_or_create_chat(cb=None):
    def return_view():
        global LOG_LEVEL
        G.CHAT_VIEW_PATH = G.CHAT_VIEW.file_name()
        G.CHAT_VIEW.set_read_only(True)
        if G.DEBUG:
            LOG_LEVEL = LOG_LEVELS['DEBUG']
        if cb:
            return cb(G.CHAT_VIEW)

    def open_view():
        if not G.CHAT_VIEW:
            p = os.path.join(G.COLAB_DIR, 'msgs.floobits.log')
            G.CHAT_VIEW = G.ROOM_WINDOW.open_file(p)

        if G.CHAT_VIEW.is_loading():
            return sublime.set_timeout(open_view, 50)

        sublime.set_timeout(return_view, 0)

    # Can't call open_file outside main thread
    sublime.set_timeout(open_view, 0)


class MSG(object):
    def __init__(self, msg, timestamp=None, username=None, level=LOG_LEVELS['MSG']):
        self.msg = msg
        self.timestamp = timestamp or time.time()
        self.username = username
        self.level = level

    def display(self):
        if self.level < LOG_LEVEL:
            return

        def _display(view):
            with utils.edit(view) as ed:
                size = view.size()
                view.set_read_only(False)
                view.insert(ed, size, str(self))
                view.set_read_only(True)
                # TODO: this scrolling is lame and centers text :/
                view.show(size)

        get_or_create_chat(_display)

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

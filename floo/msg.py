import time

import sublime

import utils

LOG_LEVELS = {
    'DEBUG': 1,
    'MSG': 2,
    'WARN': 3,
    'ERROR': 4,
}

LOG_LEVEL = LOG_LEVELS['MSG']


class MSG(object):
    def __init__(self, msg, timestamp=None, username=None, level=LOG_LEVELS['MSG']):
        self.msg = msg
        self.timestamp = timestamp or time.time()
        self.username = username
        self.level = level

    def display(self):
        if self.level < LOG_LEVEL:
            return
        def get_or_create_chat():
            view = utils.get_or_create_chat()
            sublime.set_timeout(lambda: _display(view), 0)
        def _display(view):
            with utils.edit(view) as ed:
                size = view.size()
                view.set_read_only(False)
                view.insert(ed, size, str(self))
                view.set_read_only(True)
                # TODO: this scrolling is lame and centers text :/
                view.show(size)

        sublime.set_timeout(get_or_create_chat, 0)

    def __str__(self):
        if self.username:
            msg = "[{time}] <{user}> {msg}\n"
        else:
            msg = "[{time}] {msg}\n"
        return msg.format(user=self.username, time=time.ctime(self.timestamp), msg=self.msg)


# TODO: use introspection?
def debug(message):
    MSG(message, level=LOG_LEVELS['DEBUG']).display()


def log(message):
    MSG(message, level=LOG_LEVELS['MSG']).display()


def warn(message):
    MSG(message, level=LOG_LEVELS['WARN']).display()


def error(message):
    MSG(message, level=LOG_LEVELS['ERROR']).display()

import time

import sublime

import utils


class MSG(object):
    def __init__(self, timestamp, msg, username=None):
        self.username = username
        self.msg = msg
        self.timestamp = timestamp

    def display(self):
        def _display():
            with utils.edit(view) as ed:
                size = view.size()
                view.set_read_only(False)
                view.insert(ed, size, str(self))
                view.set_read_only(True)
                # TODO: this scrolling is lame and centers text :/
                view.show(size)

        view = utils.get_or_create_chat()
        sublime.set_timeout(_display, 0)

    def __str__(self):
        if self.username:
            msg = "[{time}] <{user}> {msg}\n"
        else:
            msg = "[{time}] {msg}\n"
        return msg.format(user=self.username, time=time.ctime(self.timestamp), msg=self.msg)

import os
import time

try:
    from . import shared as G, utils
    assert G and utils
    unicode = str
    python2 = False
except ImportError:
    python2 = True
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
    global LOG_LEVEL
    if G.DEBUG:
        LOG_LEVEL = LOG_LEVELS['DEBUG']

    def return_view():
        G.CHAT_VIEW_PATH = G.CHAT_VIEW.file_name()
        G.CHAT_VIEW.set_read_only(True)
        if cb:
            return cb(G.CHAT_VIEW)

    def open_view():
        if not G.CHAT_VIEW:
            p = os.path.join(G.COLAB_DIR, 'msgs.floobits.log')
            G.CHAT_VIEW = G.WORKSPACE_WINDOW.open_file(p)
        utils.set_timeout(return_view, 0)

    # Can't call open_file outside main thread
    if G.LOG_TO_CONSOLE:
        if cb:
            return cb(None)
    else:
        utils.set_timeout(open_view, 0)


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
            view.run_command('floo_view_set_msg', {'data': unicode(self)})

        if G.LOG_TO_CONSOLE:
            # TODO: REMOVE ME
            try:
                fd = open(os.path.join(G.COLAB_DIR, 'msgs.floobits.log'), "a+")
                fd.write(unicode(self))
                fd.close()
            except Exception as e:
                print(unicode(e))
            print(unicode(self))
        else:
            get_or_create_chat(_display)

    def __str__(self):
        if python2:
            return self.__unicode__().encode('utf-8')
        return self.__unicode__()

    def __unicode__(self):
        if self.username:
            msg = '[{time}] <{user}> {msg}\n'
        else:
            msg = '[{time}] {msg}\n'
        return unicode(msg).format(user=self.username, time=time.ctime(self.timestamp), msg=self.msg)


def msg_format(message, *args, **kwargs):
    message += ' '.join([unicode(x) for x in args])
    if kwargs:
        message = unicode(message).format(**kwargs)
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

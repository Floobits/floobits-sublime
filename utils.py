import os
import json
import re
import hashlib

try:
    from urllib.parse import urlparse
    assert urlparse
except ImportError:
    from urlparse import urlparse

try:
    import sublime
except ImportError:
    from .. import sublime

try:
    from . import shared as G
    from .lib import DMP
    assert G and DMP
except ImportError:
    import shared as G
    from lib import DMP

top_timeout_id = 0
cancelled_timeouts = set()
timeouts = set()


class FlooPatch(object):
    def __init__(self, current, buf):
        self.buf = buf
        self.current = current
        self.previous = buf['buf']
        if buf['encoding'] == 'base64':
            self.md5_before = hashlib.md5(self.previous).hexdigest()
        else:
            self.md5_before = hashlib.md5(self.previous.encode('utf-8')).hexdigest()

    def __str__(self):
        return '%s - %s' % (self.buf['id'], self.buf['path'])

    def patches(self):
        return DMP.patch_make(self.previous, self.current)

    def to_json(self):
        patches = self.patches()
        if len(patches) == 0:
            return None
        patch_str = ''
        for patch in patches:
            patch_str += str(patch)

        if self.buf['encoding'] == 'base64':
            md5_after = hashlib.md5(self.current).hexdigest()
        else:
            md5_after = hashlib.md5(self.current.encode('utf-8')).hexdigest()

        return {
            'id': self.buf['id'],
            'md5_after': md5_after,
            'md5_before': self.md5_before,
            'path': self.buf['path'],
            'patch': patch_str,
            'name': 'patch'
        }


class Waterfall(object):
    def __init__(self):
        self.chain = []

    def add(self, f, *args, **kwargs):
        self.chain.append(lambda: f(*args, **kwargs))

    def call(self):
        res = [f() for f in self.chain]
        self.chain = []
        return res


def reload_settings():
    print('Reloading settings...')
    floorc_settings = load_floorc()
    for name, val in floorc_settings.items():
        setattr(G, name, val)
    G.COLAB_DIR = G.SHARE_DIR or os.path.join(G.BASE_DIR, 'share')
    G.COLAB_DIR = os.path.expanduser(G.COLAB_DIR)
    G.COLAB_DIR = os.path.realpath(G.COLAB_DIR)
    mkdir(G.COLAB_DIR)
    print('Floobits debug is %s' % G.DEBUG)


def load_floorc():
    """try to read settings out of the .floorc file"""
    s = {}
    try:
        fd = open(G.FLOORC_PATH, 'rb')
    except IOError as e:
        if e.errno == 2:
            return s
        raise

    default_settings = fd.read().decode('utf-8').split('\n')
    fd.close()

    for setting in default_settings:
        # TODO: this is horrible
        if len(setting) == 0 or setting[0] == '#':
            continue
        try:
            name, value = setting.split(' ', 1)
        except IndexError:
            continue
        s[name.upper()] = value
    return s


def set_timeout(func, timeout, *args, **kwargs):
    global top_timeout_id
    timeout_id = top_timeout_id
    top_timeout_id += 1
    if top_timeout_id > 100000:
        top_timeout_id = 0

    def timeout_func():
        timeouts.remove(timeout_id)
        if timeout_id in cancelled_timeouts:
            cancelled_timeouts.remove(timeout_id)
            return
        func(*args, **kwargs)
    sublime.set_timeout(timeout_func, timeout)
    timeouts.add(timeout_id)
    return timeout_id


def cancel_timeout(timeout_id):
    if timeout_id in timeouts:
        cancelled_timeouts.add(timeout_id)


def parse_url(workspace_url):
    secure = G.SECURE
    owner = None
    workspace_name = None
    parsed_url = urlparse(workspace_url)
    port = parsed_url.port
    if parsed_url.scheme == 'http':
        if not port:
            port = 3148
        secure = False
    result = re.match('^/r/([-\@\+\.\w]+)/([-\w]+)/?$', parsed_url.path)
    if result:
        (owner, workspace_name) = result.groups()
    else:
        raise ValueError('%s is not a valid Floobits URL' % workspace_url)
    return {
        'host': parsed_url.hostname,
        'owner': owner,
        'port': port,
        'workspace': workspace_name,
        'secure': secure,
    }


def to_workspace_url(r):
    port = int(r['port'])
    if r['secure']:
        proto = 'https'
        if port == 3448:
            port = ''
    else:
        proto = 'http'
        if port == 3148:
            port = ''
    if port != '':
        port = ':%s' % port
    workspace_url = '%s://%s%s/r/%s/%s/' % (proto, r['host'], port, r['owner'], r['workspace'])
    return workspace_url


def get_full_path(p):
    full_path = os.path.join(G.PROJECT_PATH, p)
    return unfuck_path(full_path)


def unfuck_path(p):
    return os.path.normcase(os.path.normpath(p))


def to_rel_path(p):
    return os.path.relpath(p, G.PROJECT_PATH).replace(os.sep, '/')


def to_scheme(secure):
    if secure is True:
        return 'https'
    return 'http'


def is_shared(p):
    if not G.JOINED_WORKSPACE:
        return False
    p = unfuck_path(p)
    if to_rel_path(p).find('../') == 0:
        return False
    return True


def get_persistent_data(per_path=None):
    per_data = {'recent_workspaces': [], 'workspaces': {}}
    per_path = per_path or os.path.join(G.BASE_DIR, 'persistent.json')
    try:
        per = open(per_path, 'rb')
    except (IOError, OSError):
        print('Failed to open %s. Recent workspace list will be empty.' % per_path)
        return per_data
    try:
        data = per.read().decode('utf-8')
        persistent_data = json.loads(data)
    except Exception as e:
        print('Failed to parse %s. Recent workspace list will be empty.' % per_path)
        print(e)
        print(data)
        return per_data
    if 'recent_workspaces' not in persistent_data:
        persistent_data['recent_workspaces'] = []
    if 'workspaces' not in persistent_data:
        persistent_data['workspaces'] = {}
    return persistent_data


def update_persistent_data(data):
    per_path = os.path.join(G.BASE_DIR, 'persistent.json')
    with open(per_path, 'wb') as per:
        per.write(json.dumps(data, indent=2).encode('utf-8'))


def rm(path):
    """removes path and dirs going up until a OSError"""
    os.remove(path)
    try:
        os.removedirs(os.path.split(path)[0])
    except OSError as e:
        if e.errno != 66:
            sublime.error_message('Cannot delete directory {0}.\n{1}'.format(path, e))
            raise


def mkdir(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno != 17:
            sublime.error_message('Cannot create directory {0}.\n{1}'.format(path, e))
            raise


def iter_n_deque(deque, n=10):
    i = 0
    while i < n:
        try:
            yield deque.popleft()
        except IndexError:
            return
        i += 1

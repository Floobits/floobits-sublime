import os
import json
import re

try:
    from urllib.parse import urlparse
    assert urlparse
except ImportError:
    from urlparse import urlparse

import sublime

try:
    from . import shared as G
    assert G
except ImportError:
    import shared as G

top_timeout_id = 0
cancelled_timeouts = set()
timeouts = set()


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


def get_workspace_window():
    workspace_window = None
    for w in sublime.windows():
        for f in w.folders():
            if f == G.PROJECT_PATH:
                workspace_window = w
                break
    return workspace_window


def set_workspace_window(cb):
    workspace_window = get_workspace_window()
    if workspace_window is None:
        return set_timeout(set_workspace_window, 50, cb)
    G.WORKSPACE_WINDOW = workspace_window
    cb()


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
    if not G.CONNECTED:
        return False
    p = unfuck_path(p)
    if to_rel_path(p).find("../") == 0:
        return False
    return True


def get_persistent_data(per_path=None):
    per_path = per_path or os.path.join(G.BASE_DIR, 'persistent.json')
    try:
        per = open(per_path, 'rb')
    except (IOError, OSError):
        print('Failed to open %s. Recent workspace list will be empty.' % per_path)
        return {}
    try:
        data = per.read().decode('utf-8')
        persistent_data = json.loads(data)
    except Exception as e:
        print('Failed to parse %s. Recent workspace list will be empty.' % per_path)
        print(e)
        print(data)
        return {}
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

import sys
import base64

import sublime

try:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    assert Request and urlencode and urlopen
except ImportError:
    from urllib import urlencode
    from urllib2 import Request, urlopen


try:
    from . import shared as G, utils
    assert G and utils
except ImportError:
    import shared as G
    import utils


def get_basic_auth():
    # TODO: use api_key if it exists
    basic_auth = ('%s:%s' % (G.USERNAME, G.SECRET)).encode('utf-8')
    basic_auth = base64.encodestring(basic_auth)
    return basic_auth.decode('ascii').replace('\n', '')


# TODO: include version of plugin in user agent
def api_request(url, data=None):
    if data:
        data = urlencode(data).encode('utf-8')
    r = Request(url, data=data)
    r.add_header('Authorization', 'Basic %s' % get_basic_auth())
    r.add_header('User-Agent', 'Floobits Sublime Plugin %s py-%s.%s' % (sublime.platform(), sys.version_info[0], sys.version_info[1]))
    return urlopen(r, timeout=5)


# TODO: let people create org workspaces
def create_workspace(post_data):
    url = 'https://%s/api/workspace/' % G.DEFAULT_HOST
    return api_request(url, post_data)


def get_workspace_by_url(url):
    result = utils.parse_url(url)
    api_url = 'https://%s/api/workspace/%s/%s' % (result['host'], result['owner'], result['workspace'])
    return api_request(api_url)


def get_workspace(owner, workspace):
    api_url = 'https://%s/api/workspace/%s/%s' % (G.DEFAULT_HOST, owner, workspace)
    return api_request(api_url)


def send_error(data):
    try:
        api_url = 'https://%s/api/error/' % (G.DEFAULT_HOST)
        return api_request(api_url, data)
    except Exception as e:
        print(e)
    return None

import sys
import base64
import imp
import json

try:
    import sublime
except ImportError:
    from .. import sublime

try:
    import urllib
    imp.reload(urllib)
    from urllib import request
    imp.reload(request)
    Request = request.Request
    urlopen = request.urlopen
    assert Request and urlopen
except ImportError:
    import urllib2
    imp.reload(urllib2)
    Request = urllib2.Request
    urlopen = urllib2.urlopen


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


def api_request(url, data=None):
    if data:
        data = json.dumps(data).encode('utf-8')
    r = Request(url, data=data)
    r.add_header('Authorization', 'Basic %s' % get_basic_auth())
    r.add_header('Accept', 'application/json')
    r.add_header('Content-type', 'application/json')
    r.add_header('User-Agent', 'Floobits Sublime Plugin %s %s py-%s.%s' % (G.__PLUGIN_VERSION__, sublime.platform(), sys.version_info[0], sys.version_info[1]))
    return urlopen(r, timeout=5)


def create_workspace(post_data):
    url = 'https://%s/api/workspace/' % G.DEFAULT_HOST
    return api_request(url, post_data)


def get_workspace_by_url(url):
    result = utils.parse_url(url)
    api_url = 'https://%s/api/workspace/%s/%s/' % (result['host'], result['owner'], result['workspace'])
    return api_request(api_url)


def get_workspace(owner, workspace):
    api_url = 'https://%s/api/workspace/%s/%s/' % (G.DEFAULT_HOST, owner, workspace)
    return api_request(api_url)


def get_workspaces():
    api_url = 'https://%s/api/workspace/can/view/' % (G.DEFAULT_HOST)
    return api_request(api_url)


def get_orgs():
    api_url = 'https://%s/api/orgs/' % (G.DEFAULT_HOST)
    return api_request(api_url)


def get_orgs_can_admin():
    api_url = 'https://%s/api/orgs/can/admin/' % (G.DEFAULT_HOST)
    return api_request(api_url)


def send_error(data):
    try:
        api_url = 'https://%s/api/error/' % (G.DEFAULT_HOST)
        return api_request(api_url, data)
    except Exception as e:
        print(e)
    return None

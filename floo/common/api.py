import sys
import base64
import json
import subprocess

try:
    import ssl
except ImportError:
    ssl = False


try:
    str_instances = (str, basestring)
except Exception:
    str_instances = (str, )

try:
    import urllib
    from urllib.request import Request, urlopen
    HTTPError = urllib.error.HTTPError
    URLError = urllib.error.URLError
except (AttributeError, ImportError, ValueError):
    import urllib2
    from urllib2 import Request, urlopen
    HTTPError = urllib2.HTTPError
    URLError = urllib2.URLError

try:
    from .. import editor
    from . import msg, shared as G, utils
except ImportError:
    import editor
    import msg
    import shared as G
    import utils


def get_basic_auth():
    basic_auth = ('%s:%s' % (G.USERNAME, G.SECRET)).encode('utf-8')
    basic_auth = base64.encodestring(basic_auth)
    return basic_auth.decode('ascii').replace('\n', '')


class APIResponse():
    def __init__(self, r):
        if isinstance(r, bytes):
            r = r.decode('utf-8')
        if isinstance(r, str_instances):
            lines = r.split('\n')
            self.code = int(lines[0])
            self.body = json.loads('\n'.join(lines[1:]))
        else:
            self.code = r.code
            self.body = json.loads(r.read().decode("utf-8"))


def proxy_api_request(url, data=None):
    args = ['python', '-m', 'floo.proxy', '--url', url]
    if data:
        args += ["--data", json.dumps(data)]
    msg.log('Running %s (%s)' % (' '.join(args), G.PLUGIN_PATH))
    proc = subprocess.Popen(args, cwd=G.PLUGIN_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (stdout, stderr) = proc.communicate()
    if stderr:
        raise IOError(stderr)

    if proc.poll() != 0:
        raise IOError(stdout)
    r = APIResponse(stdout)
    return r


def hit_url(url, data=None):
    if data:
        data = json.dumps(data).encode('utf-8')
    r = Request(url, data=data)
    r.add_header('Authorization', 'Basic %s' % get_basic_auth())
    r.add_header('Accept', 'application/json')
    r.add_header('Content-type', 'application/json')
    r.add_header('User-Agent', 'Floobits Plugin %s %s %s py-%s.%s' % (
        editor.name(),
        G.__PLUGIN_VERSION__,
        editor.platform(),
        sys.version_info[0],
        sys.version_info[1]
    ))
    return urlopen(r, timeout=5)


def api_request(url, data=None):
    if ssl is False:
        return proxy_api_request(url, data)
    try:
        r = hit_url(url, data)
    except HTTPError as e:
        r = e
    return APIResponse(r)


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

import sys
import base64
import json
import subprocess
import traceback
from functools import wraps

try:
    import ssl
except ImportError:
    ssl = False


try:
    import __builtin__
    str_instances = (str, __builtin__.basestring)
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
    from .exc_fmt import str_e
except ImportError:
    import editor
    import msg
    import shared as G
    import utils
    from exc_fmt import str_e


def get_basic_auth(host):
    username = G.AUTH.get(host, {}).get('username')
    secret = G.AUTH.get(host, {}).get('secret')
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


def proxy_api_request(url, data, method):
    args = ['python', '-m', 'floo.proxy', '--url', url]
    if data:
        args += ["--data", json.dumps(data)]
    if method:
        args += ["--method", method]
    msg.log('Running %s (%s)' % (' '.join(args), G.PLUGIN_PATH))
    proc = subprocess.Popen(args, cwd=G.PLUGIN_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (stdout, stderr) = proc.communicate()
    if stderr:
        raise IOError(stderr)

    if proc.poll() != 0:
        raise IOError(stdout)
    r = APIResponse(stdout)
    return r


def user_agent():
    return 'Floobits Plugin %s %s %s py-%s.%s' % (
        editor.name(),
        G.__PLUGIN_VERSION__,
        editor.platform(),
        sys.version_info[0],
        sys.version_info[1]
    )


def hit_url(url, data, method):
    if data:
        data = json.dumps(data).encode('utf-8')
    r = Request(url, data=data)
    r.method = method
    r.get_method = lambda: method
    r.add_header('Authorization', 'Basic %s' % get_basic_auth())
    r.add_header('Accept', 'application/json')
    r.add_header('Content-type', 'application/json')
    r.add_header('User-Agent', user_agent())
    return urlopen(r, timeout=5)


def api_request(url, data=None, method=None):
    if data:
        method = method or 'POST'
    else:
        method = method or 'GET'
    if ssl is False:
        return proxy_api_request(url, data, method)
    try:
        r = hit_url(url, data, method)
    except HTTPError as e:
        r = e
    return APIResponse(r)


def create_workspace(host, post_data):
    api_url = 'https://%s/api/workspace' % host
    return api_request(api_url, post_data)


def update_workspace(host, owner, workspace, data):
    api_url = 'https://%s/api/workspace/%s/%s' % (host, owner, workspace)
    return api_request(api_url, data, method='PUT')


def get_workspace_by_url(url):
    result = utils.parse_url(url)
    api_url = 'https://%s/api/workspace/%s/%s' % (result['host'], result['owner'], result['workspace'])
    return api_request(api_url)


def get_workspace(host, owner, workspace):
    api_url = 'https://%s/api/workspace/%s/%s' % (host, owner, workspace)
    return api_request(api_url)


def get_workspaces(host):
    api_url = 'https://%s/api/workspace/can/view' % (host)
    return api_request(api_url)


def get_orgs(host):
    api_url = 'https://%s/api/orgs' % (host)
    return api_request(api_url)


def get_orgs_can_admin(host):
    api_url = 'https://%s/api/orgs/can/admin' % (host)
    return api_request(api_url)


def send_error(description=None, exception=None):
    G.ERROR_COUNT += 1
    if G.ERRORS_SENT >= G.MAX_ERROR_REPORTS:
        msg.warn('Already sent %s errors this session. Not sending any more.' % G.ERRORS_SENT)
        return
    data = {
        'jsondump': {
            'error_count': G.ERROR_COUNT
        },
        'message': {},
        'username': G.USERNAME,
        'dir': G.COLAB_DIR,
    }
    if G.AGENT:
        data['owner'] = G.AGENT.owner
        data['workspace'] = G.AGENT.workspace
    if exception:
        data['message'] = {
            'description': str(exception),
            'stack': traceback.format_exc(exception)
        }
    msg.log('Floobits plugin error! Sending exception report: %s' % data['message'])
    if description:
        data['message']['description'] = description
    try:
        api_url = 'https://%s/api/log' % (G.DEFAULT_HOST)
        r = api_request(api_url, data)
        G.ERRORS_SENT += 1
        return r
    except Exception as e:
        print(e)


def send_errors(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            send_error(None, e)
            raise
    return wrapped


def prejoin_workspace(workspace_url, dir_to_share, api_args):
    try:
        result = utils.parse_url(workspace_url)
    except Exception as e:
        msg.error(str_e(e))
        return False
    try:
        w = get_workspace_by_url(workspace_url)
    except Exception as e:
        editor.error_message('Error opening url %s: %s' % (workspace_url, str_e(e)))
        return False

    if w.code >= 400:
        try:
            d = utils.get_persistent_data()
            try:
                del d['workspaces'][result['owner']][result['name']]
            except Exception:
                pass
            try:
                del d['recent_workspaces'][workspace_url]
            except Exception:
                pass
            utils.update_persistent_data(d)
        except Exception as e:
            msg.debug(str_e(e))
        return False

    msg.debug('workspace: %s', json.dumps(w.body))
    anon_perms = w.body.get('perms', {}).get('AnonymousUser', [])
    msg.debug('api args: %s' % api_args)
    new_anon_perms = api_args.get('perms', {}).get('AnonymousUser', [])
    # TODO: prompt/alert user if going from private to public
    if set(anon_perms) != set(new_anon_perms):
        msg.debug(str(anon_perms), str(new_anon_perms))
        w.body['perms']['AnonymousUser'] = new_anon_perms
        response = update_workspace(w.body['owner'], w.body['name'], w.body)
        msg.debug(str(response.body))
    utils.add_workspace_to_persistent_json(w.body['owner'], w.body['name'], workspace_url, dir_to_share)
    return result

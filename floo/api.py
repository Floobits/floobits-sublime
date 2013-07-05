import base64

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
    basic_auth = ('%s:%s' % (G.USERNAME, G.SECRET)).encode('utf-8')
    basic_auth = base64.encodestring(basic_auth)
    return basic_auth.decode('ascii').replace('\n', '')


# TODO: let people create org workspaces
def create_workspace(workspace_name):
    url = 'https://%s/api/workspace/' % G.DEFAULT_HOST
    # TODO: let user specify permissions
    post_data = {
        'name': workspace_name
    }
    r = Request(url, data=urlencode(post_data).encode('utf-8'))
    r.add_header('Authorization', 'Basic %s' % get_basic_auth())
    return urlopen(r, timeout=5)


def get_workspace_by_url(url):
    result = utils.parse_url(url)
    api_url = 'https://%s/api/workspace/%s/%s' % (result['host'], result['owner'], result['workspace'])
    r = Request(api_url)
    r.add_header('Authorization', 'Basic %s' % get_basic_auth())
    return urlopen(r, timeout=5)


def get_workspace(owner, workspace):
    url = 'https://%s/api/workspace/%s/%s' % (G.DEFAULT_HOST, owner, workspace)
    r = Request(url)
    r.add_header('Authorization', 'Basic %s' % get_basic_auth())
    return urlopen(r, timeout=5)

import base64

try:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    assert Request and urlencode and urlopen
except ImportError:
    from urllib import urlencode
    from urllib2 import Request, urlopen


try:
    from . import shared as G
    assert G
except ImportError:
    import shared as G


def create_workspace(workspace_name):
    url = 'https://%s/api/workspace/' % G.DEFAULT_HOST
    # TODO: let user specify permissions
    post_data = {
        'name': workspace_name
    }
    r = Request(url, data=urlencode(post_data).encode('utf-8'))
    basic_auth = ('%s:%s' % (G.USERNAME, G.SECRET)).encode('utf-8')
    basic_auth = base64.encodestring(basic_auth)
    basic_auth = basic_auth.decode('ascii').replace('\n', '')
    r.add_header('Authorization', 'Basic %s' % basic_auth)
    urlopen(r, timeout=5)

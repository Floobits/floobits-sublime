try:
    from urllib.parse import urlencode
    from urllib.request import urlopen
    assert urlencode, urlopen
except ImportError:
    from urllib import urlencode
    from urllib2 import urlopen


try:
    from . import shared as G
    assert G
except ImportError:
    import shared as G


def create_workspace(workspace_name):
    url = 'https://%s/api/workspace/' % G.DEFAULT_HOST
    # TODO: let user specify permissions
    post_data = {
        'username': G.USERNAME,
        'secret': G.SECRET,
        'name': workspace_name
    }
    urlopen(url, data=urlencode(post_data).encode('ascii'), timeout=5)

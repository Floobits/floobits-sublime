from urllib.parse import urlencode
import urllib.error
import urllib.request

from . import shared as G


def create_room(room_name):
    url = 'https://%s/api/room/' % G.DEFAULT_HOST
    # TODO: let user specify permissions
    post_data = {
        'username': G.USERNAME,
        'secret': G.SECRET,
        'name': room_name
    }
    urllib.request.urlopen(url, data=urlencode(post_data).encode('ascii'), timeout=5)

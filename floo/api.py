import urllib2

import sublime

import shared as G

def create_room(room_name):
    url = 'https://%s/api/room' % G.DEFAULT_HOST
    # TODO: let user specify permissions
    post_data = {
        'username': G.USERNAME,
        'secret': G.SECRET,
        'name': room_name
    }
    urllib2.urlopen(url, data=post_data, timeout=5)

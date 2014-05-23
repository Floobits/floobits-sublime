# coding: utf-8
import sys
import os
import subprocess
import threading

import sublime

PY2 = sys.version_info < (3, 0)

if PY2 and sublime.platform() == 'windows':
    err_msg = '''Sorry, but the Windows version of Sublime Text 2 lacks Python's select module, so the Floobits plugin won't work.
Please upgrade to Sublime Text 3. :('''
    raise(Exception(err_msg))
elif sublime.platform() == 'osx':
    try:
        p = subprocess.Popen(['/usr/bin/sw_vers', '-productVersion'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result = p.communicate()
        if float(result[0][:4]) < 10.7:
            sublime.error_message('''Sorry, but the Floobits plugin doesn\'t work on 10.6 or earlier.
Please upgrade your operating system if you want to use this plugin. :(''')
    except Exception as e:
        print(e)

try:
    from .floo import version
    from .floo.listener import Listener
    from .floo.common import reactor, shared as G, utils
    from .floo.common.exc_fmt import str_e
    assert utils
except (ImportError, ValueError):
    from floo import version
    from floo.listener import Listener
    from floo.common import reactor, shared as G, utils
    from floo.common.exc_fmt import str_e

reactor = reactor.reactor


try:
    from text_commands import FlooViewReplaceRegion, FlooViewReplaceRegions
    from window_commands import *
    assert FlooViewReplaceRegion and FlooViewReplaceRegions
except:
    from .window_commands import *
    from .text_commands import FlooViewReplaceRegion, FlooViewReplaceRegions

assert FlooViewReplaceRegion and FlooViewReplaceRegions and Listener and version


def global_tick():
    # XXX: A couple of sublime 2 users have had reactor == None here
    reactor.tick()
    utils.set_timeout(global_tick, G.TICK_TIME)


called_plugin_loaded = False


# Sublime 3 calls this once the plugin API is ready
def plugin_loaded():
    global called_plugin_loaded
    if called_plugin_loaded:
        return
    called_plugin_loaded = True
    print('Floobits: Called plugin_loaded.')

    utils.reload_settings()

    # TODO: one day this can be removed (once all our users have updated)
    old_colab_dir = os.path.realpath(os.path.expanduser(os.path.join('~', '.floobits')))
    if os.path.isdir(old_colab_dir) and not os.path.exists(G.BASE_DIR):
        print('renaming %s to %s' % (old_colab_dir, G.BASE_DIR))
        os.rename(old_colab_dir, G.BASE_DIR)
        os.symlink(G.BASE_DIR, old_colab_dir)

    try:
        utils.normalize_persistent_data()
    except Exception as e:
        print('Floobits: Error normalizing persistent data:', str_e(e))
        # Keep on truckin' I guess

    d = utils.get_persistent_data()
    G.AUTO_GENERATED_ACCOUNT = d.get('auto_generated_account', False)

    can_auth = (G.USERNAME or G.API_KEY) and G.SECRET
    # Sublime plugin API stuff can't be called right off the bat
    if not can_auth:
        utils.set_timeout(create_or_link_account, 1)

    utils.set_timeout(global_tick, 1)

# Sublime 2 has no way to know when plugin API is ready. Horrible hack here.
if PY2:
    for i in range(0, 20):
        threading.Timer(i, utils.set_timeout, [plugin_loaded, 1]).start()

    def warning():
        if not called_plugin_loaded:
            print('Your computer is slow and could not start the Floobits reactor.  Please contact us or upgrade to Sublime Text 3.')
    threading.Timer(20, warning).start()

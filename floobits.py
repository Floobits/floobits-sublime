# coding: utf-8
import sys
import os
import time
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
        v = float(result[0].decode('utf-8').split('.')[1])
        print('Floobits detected OS X 10.%.0f' % v)
        if v < 7:
            sublime.error_message('''Sorry, but the Floobits plugin doesn\'t work on 10.6 or earlier.
Please upgrade your operating system if you want to use this plugin. :(''')
    except Exception as e:
        print(e)

try:
    from .floo import version
    from .floo.listener import Listener
    from .floo.common import migrations, reactor, shared as G, utils
    from .floo.common.exc_fmt import str_e
    assert utils
except (ImportError, ValueError):
    from floo import version
    from floo.listener import Listener
    from floo.common import migrations, reactor, shared as G, utils
    from floo.common.exc_fmt import str_e
assert Listener and version

reactor = reactor.reactor
called_plugin_loaded = False


@utils.inlined_callbacks
def setup():
    # hop into main thread
    try:
        yield lambda cb: sublime.set_timeout(cb, 50)

        while True:
            # stupid yielding loop until we get a window from st2
            w = sublime.active_window()
            if w is not None:
                break
            yield lambda cb: sublime.set_timeout(cb, 50)
        settings = sublime.load_settings("myplugin.sublime-settings")
        now = time.time()
        old_time = settings.get("floobits-id")
        settings.set("floobits-id", now)
        interval = utils.set_interval(reactor.tick, G.TICK_TIME)

        def shutdown():
            print("shutting down old instance", old_time)
            utils.cancel_timeout(interval)

        settings.add_on_change("floobits-id", shutdown)
        w.run_command("floobits_setup")
    except Exception as e:
        print(str_e(e))


# Sublime 3 calls this once the plugin API is ready
def plugin_loaded():
    global called_plugin_loaded
    if called_plugin_loaded:
        return
    print('loaded')
    called_plugin_loaded = True
    print('Floobits: Called plugin_loaded.')

    if not os.path.exists(G.FLOORC_JSON_PATH):
        migrations.migrate_floorc()
    utils.reload_settings()

    # TODO: one day this can be removed (once all our users have updated)
    old_colab_dir = os.path.realpath(os.path.expanduser(os.path.join('~', '.floobits')))
    if os.path.isdir(old_colab_dir) and not os.path.exists(G.BASE_DIR):
        print('Renaming %s to %s' % (old_colab_dir, G.BASE_DIR))
        os.rename(old_colab_dir, G.BASE_DIR)
        os.symlink(G.BASE_DIR, old_colab_dir)

    try:
        utils.normalize_persistent_data()
    except Exception as e:
        print('Floobits: Error normalizing persistent data:', str_e(e))
        # Keep on truckin' I guess

    d = utils.get_persistent_data()
    G.AUTO_GENERATED_ACCOUNT = d.get('auto_generated_account', False)
    setup()

# Sublime 2 has no way to know when plugin API is ready. Horrible hack here.
if PY2:
    for i in range(0, 20):
        threading.Timer(i, utils.set_timeout, [plugin_loaded, 1]).start()

    def warning():
        if not called_plugin_loaded:
            print('Your computer is slow and could not start the Floobits reactor. ' +
                  'Please contact us (support@floobits.com) or upgrade to Sublime Text 3.')
    threading.Timer(20, warning).start()

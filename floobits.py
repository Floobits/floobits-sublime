# coding: utf-8
import sys
import os
import time
import subprocess
import threading

import sublime

PY2 = sys.version_info < (3, 0)
SOCK_SINGLE_READ = False

if PY2 and sublime.platform() == 'windows':
    try:
        import select
        assert select
        # Change behavior of some low-level socket stuff so that we don't break
        SOCK_SINGLE_READ = True
    except Exception as e:
        err_msg = '''Sorry, but the Windows version of Sublime Text 2 lacks Python's select module, so the Floobits plugin won't work.
Please upgrade to Sublime Text 3 or install Package Control 3. :('''
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
    from .floo.common import reactor, shared as G, utils
    from .floo.common.exc_fmt import str_e
    assert utils
except (ImportError, ValueError):
    from floo import version
    from floo.listener import Listener
    from floo.common import reactor, shared as G, utils
    from floo.common.exc_fmt import str_e
assert Listener and version

reactor = reactor.reactor
called_plugin_loaded = False


def setup():
    def _setup():
        # stupid yielding loop until we get a window from st2
        w = sublime.active_window()
        if w is None:
            return sublime.set_timeout(_setup, 50)

        try:
            settings = sublime.load_settings('Floobits.sublime-settings')
            now = time.time()
            old_time = settings.get('floobits-id')
            settings.set('floobits-id', now)
            interval = utils.set_interval(reactor.tick, G.TICK_TIME)

            def shutdown():
                print('Floobits plugin updated. Shutting down old instance.', old_time)
                try:
                    utils.cancel_timeout(interval)
                except Exception:
                    pass

            try:
                settings.clear_on_change('floobits-id')
            except Exception:
                pass
            settings.add_on_change('floobits-id', shutdown)
            w.run_command('floobits_setup')
        except Exception as e:
            print(str_e(e))

    # hop into main thread
    sublime.set_timeout(_setup, 50)


# Sublime 3 calls this once the plugin API is ready
def plugin_loaded():
    global called_plugin_loaded
    if called_plugin_loaded:
        return
    called_plugin_loaded = True
    print('Floobits: Called plugin_loaded.')

    utils.reload_settings()

    G.SOCK_SINGLE_READ = SOCK_SINGLE_READ

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

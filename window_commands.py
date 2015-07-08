# coding: utf-8
import sys
import os
import json
import webbrowser

import sublime_plugin
import sublime

PY2 = sys.version_info < (3, 0)

try:
    from .floo import sublime_ui
    from .floo.common import api, reactor, msg, shared as G, utils
    from .floo.common.exc_fmt import str_e
    assert api and G and msg and utils
except (ImportError, ValueError):
    from floo import sublime_ui
    from floo.common import reactor, msg, shared as G, utils
    from floo.common.exc_fmt import str_e


reactor = reactor.reactor

SublimeUI = sublime_ui.SublimeUI()


def disconnect_dialog():
    if G.AGENT and G.AGENT.joined_workspace:
        disconnect = sublime.ok_cancel_dialog('You can only be in one workspace at a time.', 'Leave %s/%s' % (G.AGENT.owner, G.AGENT.workspace))
        if disconnect:
            msg.debug('Stopping agent.')
            reactor.stop()
            G.AGENT = None
        return disconnect
    return True


class FloobitsBaseCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return True

    def is_enabled(self):
        return bool(G.AGENT and G.AGENT.is_ready())


class FloobitsOpenSettingsCommand(sublime_plugin.WindowCommand):
    def run(self):
        window = sublime.active_window()
        if window:
            window.open_file(G.FLOORC_JSON_PATH)


class FloobitsShareDirCommand(FloobitsBaseCommand):
    def is_enabled(self):
        return not super(FloobitsShareDirCommand, self).is_enabled()

    def run(self, dir_to_share=None, paths=None, current_file=False, api_args=None):
        if paths:
            if len(paths) != 1:
                return sublime.error_message('Only one folder at a time, please. :(')
            return SublimeUI.share_dir(self.window, paths[0], api_args)

        if dir_to_share is None:
            folders = self.window.folders()
            if folders:
                dir_to_share = folders[0]
            else:
                dir_to_share = os.path.expanduser(os.path.join('~', 'share_me'))

        SublimeUI.prompt_share_dir(self.window, dir_to_share, api_args)


class FloobitsDeleteWorkspaceCommand(FloobitsBaseCommand):
    def is_visible(self):
        return True

    def is_enabled(self):
        return utils.can_auth()

    def run(self, force=False):
        SublimeUI.delete_workspace(self.window, lambda *args, **kwargs: None)


class FloobitsPromptJoinWorkspaceCommand(sublime_plugin.WindowCommand):

    def run(self, workspace=None):
        if workspace is None:
            workspace = 'https://%s/' % G.DEFAULT_HOST
        for d in self.window.folders():
            floo_file = os.path.join(d, '.floo')
            try:
                floo_info = open(floo_file, 'r').read()
                wurl = json.loads(floo_info).get('url')
                utils.parse_url(wurl)
                # TODO: check if workspace actually exists
                workspace = wurl
                break
            except Exception:
                pass
        self.window.show_input_panel('Workspace URL:', workspace, self.on_input, None, None)

    def on_input(self, workspace_url):
        if disconnect_dialog():
            SublimeUI.join_workspace_by_url(self.window, workspace_url, self.window.folders())


class FloobitsPinocchioCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return G.AUTO_GENERATED_ACCOUNT

    def run(self):
        floorc = utils.load_floorc_json()
        auth = floorc.get('AUTH', {}).get(G.DEFAULT_HOST, {})
        username = auth.get('username')
        secret = auth.get('secret')
        print(username, secret)
        if not (username and secret):
            return sublime.error_message('You don\'t seem to have a Floobits account of any sort')
        webbrowser.open('https://%s/%s/pinocchio/%s' % (G.DEFAULT_HOST, username, secret))


class FloobitsLeaveWorkspaceCommand(FloobitsBaseCommand):

    def run(self):
        if G.AGENT:
            message = 'You have left the workspace.'
            G.AGENT.update_status_msg(message)
            reactor.stop()
            G.AGENT = None
            # TODO: Mention the name of the thing we left
            if not G.EXPERT_MODE:
                sublime.error_message(message)
        else:
            sublime.error_message('You are not joined to any workspace.')

    def is_enabled(self):
        return bool(G.AGENT)


class FloobitsClearHighlightsCommand(FloobitsBaseCommand):
    def run(self):
        G.AGENT.clear_highlights(self.window.active_view())


class FloobitsSummonCommand(FloobitsBaseCommand):
    # TODO: ghost this option if user doesn't have permissions
    def run(self):
        G.AGENT.summon(self.window.active_view())


class FloobitsJoinRecentWorkspaceCommand(sublime_plugin.WindowCommand):
    def _get_recent_workspaces(self):
        self.persistent_data = utils.get_persistent_data()
        self.recent_workspaces = self.persistent_data['recent_workspaces']

        try:
            recent_workspaces = [x.get('url') for x in self.recent_workspaces if x.get('url') is not None]
        except Exception:
            pass
        return recent_workspaces

    def run(self, *args):
        workspaces = self._get_recent_workspaces()
        self.window.show_quick_panel(workspaces, self.on_done)

    def on_done(self, item):
        if item == -1:
            return
        workspace = self.recent_workspaces[item]
        SublimeUI.join_workspace_by_url(self.window, workspace['url'])

    def is_enabled(self):
        return bool(len(self._get_recent_workspaces()) > 0)


class FloobitsAddToWorkspaceCommand(FloobitsBaseCommand):
    def run(self, paths, current_file=False):
        if not self.is_enabled():
            return

        if paths is None and current_file:
            paths = [self.window.active_view().file_name()]

        notshared = []
        for path in paths:
            if utils.is_shared(path):
                G.AGENT.upload(path)
            else:
                notshared.append(path)

        if notshared:
            limit = 5
            sublime.error_message("The following paths are not a child of\n\n%s\n\nand will not be shared for security reasons:\n\n%s%s." %
                                  (G.PROJECT_PATH, ",\n".join(notshared[:limit]), len(notshared) > limit and ",\n..." or ""))

    def description(self):
        return 'Add file or directory to currently-joined Floobits workspace.'


class FloobitsRemoveFromWorkspaceCommand(FloobitsBaseCommand):
    def run(self, paths, current_file=False):
        if not self.is_enabled():
            return

        if paths is None and current_file:
            paths = [self.window.active_view().file_name()]

        if not hasattr(sublime, 'yes_no_cancel_dialog'):
            unlink = bool(sublime.ok_cancel_dialog('Delete? Select cancel to remove from the workspace without deleting.', 'Delete'))
        else:
            ret = sublime.yes_no_cancel_dialog("What should I do with\n%s" % "\n".join(paths[:5]), "Delete!", "Just Remove from Workspace.")
            if ret == 0:
                return
            unlink = ret == 1

        for path in paths:
            G.AGENT.delete_buf(path, unlink)

    def description(self):
        return 'Add file or directory to currently-joined Floobits workspace.'


class FloobitsCreateHangoutCommand(FloobitsBaseCommand):
    def run(self):
        owner = G.AGENT.owner
        workspace = G.AGENT.workspace
        host = G.AGENT.proto.host
        webbrowser.open('https://plus.google.com/hangouts/_?gid=770015849706&gd=%s/%s/%s' % (host, owner, workspace))

    def is_enabled(self):
        return bool(super(FloobitsCreateHangoutCommand, self).is_enabled() and G.AGENT.owner and G.AGENT.workspace)


class FloobitsPromptHangoutCommand(FloobitsBaseCommand):
    def run(self, hangout_url):
        confirm = bool(sublime.ok_cancel_dialog('This workspace is being edited in a Google+ Hangout? Do you want to join the hangout?'))
        if not confirm:
            return
        webbrowser.open(hangout_url)

    def is_visible(self):
        return False

    def is_enabled(self):
        return bool(super(FloobitsPromptHangoutCommand, self).is_enabled() and G.AGENT.owner and G.AGENT.workspace)


class FloobitsOpenWebEditorCommand(FloobitsBaseCommand):
    def run(self):
        try:
            agent = G.AGENT
            url = utils.to_workspace_url({
                'port': agent.proto.port,
                'secure': agent.proto.secure,
                'owner': agent.owner,
                'workspace': agent.workspace,
                'host': agent.proto.host,
            })
            webbrowser.open(url)
        except Exception as e:
            sublime.error_message('Unable to open workspace in web editor: %s' % str_e(e))


class FloobitsHelpCommand(FloobitsBaseCommand):
    def run(self):
        webbrowser.open('https://floobits.com/help/plugins/sublime', new=2, autoraise=True)

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


class FloobitsToggleFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        if G.FOLLOW_MODE:
            self.window.run_command('floobits_disable_follow_mode')
        else:
            self.window.run_command('floobits_enable_follow_mode')


class FloobitsEnableFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        G.FOLLOW_MODE = True
        msg.log('Follow mode enabled')
        G.AGENT.update_status_msg()
        G.AGENT.highlight()

    def is_visible(self):
        if G.AGENT:
            return self.is_enabled()
        return True

    def is_enabled(self):
        return bool(super(FloobitsEnableFollowModeCommand, self).is_enabled() and not G.FOLLOW_MODE)


class FloobitsDisableFollowModeCommand(FloobitsBaseCommand):
    def run(self):
        G.FOLLOW_MODE = False
        G.FOLLOW_USERS.clear()
        G.SPLIT_MODE = False
        msg.log('Follow mode disabled')
        G.AGENT.update_status_msg('Stopped following changes. ')

    def is_visible(self):
        return self.is_enabled()

    def is_enabled(self):
        return bool(super(FloobitsDisableFollowModeCommand, self).is_enabled() and G.FOLLOW_MODE)


class FloobitsFollowUser(FloobitsBaseCommand):
    def run(self):
        following_users = bool(G.FOLLOW_USERS)

        def f():
            if G.FOLLOW_USERS:
                G.FOLLOW_MODE = True
                G.SPLIT_MODE = False
                G.AGENT.update_status_msg('Following changes.')
            elif following_users:
                # If we were following users and now we're not, disable follow mode
                G.FOLLOW_MODE = False
                G.AGENT.update_status_msg('Stopped following changes.')

        SublimeUI.follow_user(self.window, f)


class FloobitsOpenWorkspaceSettingsCommand(FloobitsBaseCommand):
    def run(self):
        url = G.AGENT.workspace_url + '/settings'
        webbrowser.open(url, new=2, autoraise=True)

    def is_enabled(self):
        return bool(super(FloobitsOpenWorkspaceSettingsCommand, self).is_enabled() and G.PERMS and 'kick' in G.PERMS)


class RequestPermissionCommand(FloobitsBaseCommand):
    def run(self, perms, *args, **kwargs):
        G.AGENT.send({
            'name': 'request_perms',
            'perms': perms
        })

    def is_enabled(self):
        if not super(RequestPermissionCommand, self).is_enabled():
            return False
        if 'patch' in G.PERMS:
            return False
        return True


class FloobitsFollowSplit(FloobitsBaseCommand):
    def run(self):
        G.SPLIT_MODE = True
        G.FOLLOW_MODE = True
        if self.window.num_groups() == 1:
            self.window.set_layout({
                'cols': [0.0, 1.0],
                'rows': [0.0, 0.5, 1.0],
                'cells': [[0, 0, 1, 1], [0, 1, 1, 2]]
            })


class FloobitsSetupCommand(FloobitsBaseCommand):
    def is_visible(self):
        return True

    def is_enabled(self):
        return not utils.can_auth()

    def run(self, force=False):

        def f(x):
            print(x)

        SublimeUI.create_or_link_account(self.window, G.DEFAULT_HOST, force, f)


class FloobitsListUsersCommand(FloobitsBaseCommand):
    actions = [
        'Kick'
        'Follow'
    ]

    def run(self):
        self.users = []
        try:
            self.users = G.AGENT.workspace_info.get('users', [])
            # self.users = ['%s on %s' % (x.get('username'), x.get('client')) for x in G.AGENT.workspace_info['users'].values()]
        except Exception as e:
            print(e)

        users = [u for u in self.users]
        print(self.users)
        self.window.show_quick_panel(users, self.on_user_select)

    def on_user_select(self, item):
        if item == -1:
            return

        self.user = self.users[item]
        print(self.user)
        self.window.show_quick_panel(self.actions, self.on_user_action)

    def on_user_action(self, item):
        if item == -1:
            return
        action = self.actions[item]
        action()


class FloobitsNotACommand(sublime_plugin.WindowCommand):
    def run(self, *args, **kwargs):
        pass

    def is_visible(self):
        return True

    def is_enabled(self):
        return False

    def description(self):
        return

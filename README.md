# [Floobits](https://floobits.com/) plugin for Sublime Text 2 and 3

Real-time collaborative editing. Think Etherpad, but with native editors. This is the plugin for Sublime Text. We're also working on plugins for [Emacs](https://github.com/Floobits/emacs-plugin) and [Vim](https://github.com/Floobits/vim-plugin).

While the name of this repository is `sublime-text-2-plugin`, the plugin is compatible with Sublime Text 2 and Sublime Text 3.

### Development status: Reasonably stable. We dogfood it daily and rarely run into issues.

## Windows
The Python included with the Windows version of Sublime Text 2 does not have the [select](http://docs.python.org/2/library/select.html) module. This means the plugin won't work with Sublime Text 2 on Windows. Windows users must install Sublime Text 3 if they want to use this plugin.

# Installation instructions

* If you don't have one already, go to [Floobits](https://floobits.com/) and create an account (or sign in with GitHub). (It's free.)
* Clone this repository or download and extract [this tarball](https://github.com/Floobits/sublime-text-2-plugin/archive/master.zip).
* Rename the directory to "Floobits".
* In Sublime Text, go to Preferences -> Browse Packages.
* Drag, copy, or move the Floobits directory into your Packages directory.

If you'd rather create a symlink instead of copy/moving, run something like:

    ln -s ~/code/sublime-text-2-plugin ~/Library/Application\ Support/Sublime\ Text\ 3/Packages/Floobits

# Configuration

Edit your Floobits.sublime-settings file (in `Package Settings -> Floobits -> Settings - User`) and fill in the following info:

    {
      "username": "user",
      "secret": "THIS-IS-YOUR-API-KEY DO-NOT-USE-YOUR-PASSWORD",
    }

Replace user with your Floobits username. The secret is your API secret, which you can see in [your settings](https://floobits.com/dash/settings/).

# Using Floobits to Collaborate

After creating your account, you’ll want to create a room or two. A room is a collection of files and buffers that users can collaborate on.

See https://floobits.com/help for instructions on how to set up rooms and collaborate with others.

# Floobits plugin for Sublime Text 2

Real-time collaborative editing. Think Etherpad, but with Sublime Text 2.

**Sublime Text 3 Beta users:** You want the [Sublime Text 3 plugin](https://github.com/Floobits/sublime-text-2-plugin/tree/st3).

### Development status: Reasonably stable. We dogfood it daily and rarely run into issues.

## Windows
This plugin does not work on Windows. However, the [Sublime Text 3 plugin](https://github.com/Floobits/sublime-text-2-plugin/tree/st3) does. Windows users are encouraged to install Sublime Text 3. The Python included with the Windows version of Sublime Text 2 does not have the [select](http://docs.python.org/2/library/select.html) module.

# Installation instructions

* If you don't have one already, go to [Floobits](https://floobits.com/) and create an account (or sign in with GitHub). (It's free.)
* Clone this repository or download and extract [this tarball](https://github.com/Floobits/sublime-text-2-plugin/archive/master.zip).
* Rename the directory to "Floobits".
* In Sublime Text, go to Preferences -> Browse Packages.
* Drag, copy, or move the Floobits directory into your Packages directory.

If you'd rather create a symlink instead of copy/moving, run something like:

    ln -s ~/code/sublime-text-2-plugin ~/Library/Application\ Support/Sublime\ Text\ 2/Packages/Floobits

# Configuration

Edit your Floobits.sublime-settings file (in `Package Settings -> Floobits -> Settings - User`) and fill in the following info:

    {
      "username": "user",
      "secret": "THIS-IS-YOUR-API-KEY DO-NOT-USE-YOUR-PASSWORD",
    }

Replace user with your Floobits username. The secret is your API secret, which you can see in [your settings](https://floobits.com/dash/settings/).

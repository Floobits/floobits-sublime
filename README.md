# Floobits plugin for Sublime Text 2

## Development status: Really buggy. You don't want to use this yet.

# Installation instructions

* Clone this repository or download and extract a tarball.
* Rename the directory to "Floobits".
* In Sublime Text, go to Preferences -> Browse Packages.
* Drag, copy, or move the Floobits directory into your Packages directory.

If you'd rather create a symlink instead of copy/moving, run something like:

    ln -s ~/code/sublime-text-2-plugin ~/Library/Application\ Support/Sublime\ Text\ 2/Packages/Floobits

# Configuration

Edit your Floobits.sublime-settings file (in `Package Settings -> Floobits -> Settings - User`) and fill in the following info:

    {
      "username": "user",
      "secret": "THIS-IS-YOUR-API-KEY;DO-NOT-USE-YOUR-PASSWORD",
      "share_dir": "~/.floobits/shared/"
    }

Replace username with your Floobits username. The secret is your API secret, which you can see at https://floobits.com/dash/settings/

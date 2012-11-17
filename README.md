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

Create a Floobits.sublime-settings file and fill in the following info:

    {
      "share_dir": "/Users/ggreer/code/sublime-text-2-plugin/shared/",
      "username": "ggreer",
      "secret": "1234",
      "room": "test"
    }

`share_dir` must be an absolute path.

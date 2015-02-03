# [Floobits](https://floobits.com/) plugin for Sublime Text 2 & 3

Real-time collaborative editing. Think Etherpad, but with native editors. This is the plugin for Sublime Text. We also have plugins for [Emacs](https://github.com/Floobits/floobits-emacs), [Vim](https://github.com/Floobits/floobits-vim), and [IntelliJ](https://github.com/Floobits/floobits-intellij).

### Development status: Reasonably stable. We dogfood it daily and rarely run into issues.

# Installation instructions

* [Create a Floobits account](https://floobits.com/signup/) or [sign in with GitHub](https://floobits.com/login/github/?next=/dash/).
* If you have [Package Control](https://packagecontrol.io), go to Package Control → Install Package and search for Floobits. Select the Floobits package and install it.

* If you don't have Package Control (or you prefer to install the plugin manually), clone this repository or download and extract [this tarball](https://github.com/Floobits/floobits-sublime/archive/master.zip).
* Rename the directory to "Floobits".
* In Sublime Text, go to Preferences -> Browse Packages.
* Drag, copy, or move the Floobits directory into your Packages directory.

If you'd rather create a symlink instead of copy/moving, run something like:

    ln -s ~/code/floobits-sublime ~/Library/Application\ Support/Sublime\ Text\ 3/Packages/Floobits

# Configuration

All configuration settings are stored in `~/.floorc.json`. If you don’t have a `~/.floorc.json` file, the plugin will create one and open it in Sublime Text. It will also open a web page showing the minimal information you’ll need to put in your `~/.floorc.json`. After saving the file, restart Sublime Text.

# Using Floobits to Collaborate

After creating your account, you’ll want to create a workspace or two. A workspace is a collection of files and buffers that users can collaborate on.

See https://floobits.com/help/plugins/#sublime-usage for instructions on how to create workspaces and collaborate with others.


# Errata

## Windows
Sublime Text 2 on Windows requires Package Control 3.0 to be installed to function properly. This is due to a bug in the `select` module that ST2 ships by default.


## Linux
On Linux, Sublime Text 2 and 3 ship without the `_ssl` module. Installing Package Control 3.0 will install the missing elements. Otherwise we try to work around it by running an SSL proxy using the system Python.


## OS X
Our plugin doesn't work on 10.6 and earlier. This appears to be a bug in OS X. Please upgrade to a newer version.


# Help

If you have trouble setting up or using this plugin, please [contact us](https://floobits.com/help#support).

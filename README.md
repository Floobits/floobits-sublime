# [Floobits](https://floobits.com/) plugin for Sublime Text 2 & 3

Real-time collaborative editing. Think Etherpad, but with native editors. This is the plugin for Sublime Text. We also have plugins for [Emacs](https://github.com/Floobits/floobits-emacs) and [Vim](https://github.com/Floobits/floobits-vim).

### Development status: Reasonably stable. We dogfood it daily and rarely run into issues.

# Installation instructions

* If you don't have one already, go to [Floobits](https://floobits.com/) and create an account (or sign in with GitHub). (It's free.)

* If you have [Sublime Package Control](http://wbond.net/sublime_packages/package_control), go to Package Control → Install Package and search for Floobits. Select the Floobits package and install it.

* If you don't have Package Control (or you prefer to install the plugin manually), clone this repository or download and extract [this tarball](https://github.com/Floobits/floobits-sublime/archive/master.zip).
* Rename the directory to "Floobits".
* In Sublime Text, go to Preferences -> Browse Packages.
* Drag, copy, or move the Floobits directory into your Packages directory.

If you'd rather create a symlink instead of copy/moving, run something like:

    ln -s ~/code/floobits-sublime ~/Library/Application\ Support/Sublime\ Text\ 3/Packages/Floobits

# Configuration

All configuration settings are stored in `~/.floorc`. If you don’t have a `~/.floorc` file, the plugin will create one and open it in Sublime Text. It will also open a web page showing the minimal information you’ll need to put in your `~/.floorc`. After saving the file, restart Sublime Text.

# Using Floobits to Collaborate

After creating your account, you’ll want to create a workspace or two. A workspace is a collection of files and buffers that users can collaborate on.

See https://floobits.com/help/plugins/#sublime-usage for instructions on how to create workspaces and collaborate with others.


# Errata

## Windows
The Python included with the Windows version of Sublime Text 2 does not have the [select](http://docs.python.org/2/library/select.html) module. This means the plugin won't work with Sublime Text 2 on Windows. Windows users must install Sublime Text 3 if they want to use this plugin. Sorry, there's nothing we can do about this. `:(`


## Linux
On Linux, Sublime Text 2 and 3 ship with a broken SSL module. This is a known bug. We try to work around it, but we can't link against every version of OpenSSL. If you see the error, "Your version of Sublime Text can't  because it has a broken SSL module." you can try building your own SSL module.

1. Download the Python source code. For Sublime Text 3, you need [Python 3.3.2](http://python.org/ftp/python/3.3.2/Python-3.3.2.tar.bz2). For Sublime Text 2, you need [Python 2.6.8](http://www.python.org/ftp/python/2.6.8/Python-2.6.8.tar.bz2).  While you are at it, verify you have the openssl source files you need (on Debian, `sudo apt-get instal libssl-dev` might do the trick).
 
1. Extract and build the source code:

        tar xjf Python-*.tar.bz2
        cd Python-*/
        ./configure && make

1. Copy the ssl shared object to your Floobits plugin.  You may need to tweak these paths.  If you have installed the Floobits zip package into `~/.config/sublime-text-3/Installed\ Packages/Floobits.sublime-package` (the default behavior of Package Control) then you will need to unzip it or install the plugin source from github.  As of this writing, Sublime Text 3's default behavior ignores unzipped packages in `Installed\ Packages`, so you will need to unzip/install into `Packages` instead (despite the fact that [this directory is supposed to be for packages that ship with Sublime Text](http://www.sublimetext.com/docs/3/packages.html)).

        mkdir ~/.config/sublime-text-3/Packages/Floobits/lib/custom/
        cp build/lib.linux\*/\_ssl.cpython-\*m.so ~/.config/sublime-text-3/Packages/Floobits/lib/custom/\_ssl.so

1. Verify that the shared object works: Restart Sublime Text. Open the Sublime console (ctrl + `) and look for "Hooray! ssl_custom.so is a winner!"


## OS X
Our plugin doesn't work on 10.6 and earlier. This appears to be a bug in OS X. Please upgrade to a newer version.

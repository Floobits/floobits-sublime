#!/usr/bin/env python

import os
import sys


def main():
    if len(sys.argv) != 2:
        print('Usage: %s version' % sys.argv[0])
        os.system('git tag | sort -n | tail -n 1')
        sys.exit()

    version = sys.argv[1]

    with open('floo/version.py', 'r') as fd:
        version_py = fd.read().split('\n')

    version_py[0] = "PLUGIN_VERSION = '%s'" % version

    with open('floo/version.py', 'w') as fd:
        fd.write('\n'.join(version_py))

    os.system('git add packages.json floo/version.py')
    os.system('git commit -m "Tag new release: %s"' % version)
    os.system('git tag %s' % version)
    os.system('git push --tags')
    os.system('git push')


if __name__ == "__main__":
    main()

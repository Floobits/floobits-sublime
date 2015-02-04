#!/usr/bin/env python

import os
import re
import sys


def main():
    from distutils.version import StrictVersion
    if len(sys.argv) != 2:
        print('Usage: %s version' % sys.argv[0])
        versions = os.popen('git tag').read().split('\n')
        versions = [v for v in versions if re.match("\\d\\.\\d\\.\\d", v)]
        versions.sort(key=StrictVersion)
        print(versions[-1])
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

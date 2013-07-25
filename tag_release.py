#!/usr/bin/env python

import json
from datetime import datetime
import os
import sys


def main():
    with open('packages.json', 'r') as fd:
        pkg_json = json.loads(fd.read().decode('utf-8'))

    if len(sys.argv) != 2:
        print('Usage: %s %s' % (sys.argv[0], pkg_json['packages'][0]['platforms']['*'][0]['version']))
        sys.exit()

    version = sys.argv[1]

    now = datetime.now()
    pkg_json['packages'][0]['last_modified'] = now.strftime('%Y-%m-%d %H:%M:%S')
    pkg_json['packages'][0]['platforms']['*'][0]['version'] = version
    pkg_json['packages'][0]['platforms']['*'][0]['url'] = 'http://github.com/Floobits/floobits-sublime/archive/%s.zip' % version

    with open('packages.json', 'w') as fd:
        fd.write(json.dumps(pkg_json, indent=4, separators=(',', ': '), sort_keys=True))

    with open('floo/shared.py', 'r') as fd:
        shared_py = fd.read().decode('utf-8').split('\n')

    shared_py[0] = "__PLUGIN_VERSION__ = '%s'" % version

    with open('floo/shared.py', 'w') as fd:
        fd.write(('\n'.join(shared_py)).encode('utf-8'))

    os.system('git add packages.json floo/shared.py')
    os.system('git commit -m "Tag new release: %s"' % version)
    os.system('git tag %s' % version)
    os.system('git push --tags')
    os.system('git push')


if __name__ == "__main__":
    main()

#!/usr/bin/env python

import json
from datetime import datetime
import os
import sys


with open('packages.json', 'r') as fd:
    pkg_json = json.loads(fd.read())

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

os.system('git add packages.json')
os.system('git commit -m "Tag new release: %s"' % version)
os.system('git tag %s' % version)
os.system('git push --tags')
os.system('git push')

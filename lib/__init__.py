from lib import dmp_monkey
dmp_monkey.monkey_patch()

from lib import diff_match_patch
DMP = diff_match_patch.diff_match_patch()

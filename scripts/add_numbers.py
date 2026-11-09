"""Example saved script. No shell commands, files, or network access required."""
import json
import math
import sys

numbers = json.load(sys.stdin)['numbers']
print(json.dumps({'sum': math.fsum(numbers)}))

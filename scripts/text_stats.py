"""Example saved script: read JSON arguments from stdin, return JSON on stdout."""
import json
import sys

text = json.load(sys.stdin)['text']
print(json.dumps({'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())}))

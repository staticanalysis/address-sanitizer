#!/usr/bin/python2.4
import re
import sys
import string
import subprocess

addr2line_pipes = dict()

for line in sys.stdin:
  #0 0x7f6e35cf2e45  (/blah/foo.so+0x11fe45)
  match = re.match('^( *#[0-9]+ *0x[0-9a-f]+) *\((.*)\+(0x[0-9a-f]+)\)', line)
  if match:
    binary = match.group(2)
    addr = match.group(3)
    if not addr2line_pipes.has_key(binary):
      addr2line_pipes[binary] = subprocess.Popen(["addr2line", "-f", "-e", binary],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    p = addr2line_pipes[binary]
    print >>p.stdin, addr
    function_name = p.stdout.readline().rstrip()
    file_name     = p.stdout.readline().rstrip()
    for path_to_cut in sys.argv[1:]:
      file_name = re.sub(".*" + path_to_cut, "", file_name)

    print match.group(1), function_name, file_name
  else:
    print line.rstrip()

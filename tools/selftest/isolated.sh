#!/bin/bash
# Runs a command with its own localhost and its own process list, so several private copies can run at the
# same time on one machine without sharing ports 8001 / 8765 / 8766 or killing each other with pkill.
#   PT_SELFTEST_DIR=/tmp/lfx-a bash tools/selftest/isolated.sh bash tools/selftest/run.sh
# Everything started inside ends when the command ends. Private copy only; nothing here touches the live site.
exec unshare -n -p -f --mount-proc bash -c 'python3 -c "
import socket, fcntl, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fcntl.ioctl(s, 0x8914, struct.pack(\"16sH\", b\"lo\", 0x1 | 0x40))   # bring the private localhost up
" && exec "$@"' isolated "$@"

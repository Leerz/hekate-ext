#!/bin/bash
split -b 1073741824 -d -a 2 rawnand.bin rawnand.bin.
echo "Done."

#!/bin/bash
split -b 2147483648 -d -a 2 rawnand.bin rawnand.bin.
echo "Done."

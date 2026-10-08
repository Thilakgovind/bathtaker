#!/bin/sh
# Checks the C++ room logic against the Python reference. Needs python3 and g++.
cd "$(dirname "$0")" || exit 2
python3 make_trace.py || exit 2
g++ -std=c++11 -O1 -Wall -o check check.cpp || exit 2
./check trace.txt > got.txt
if diff -q expected.txt got.txt >/dev/null; then
  echo "PASS: the C++ logic gives the same $(wc -l < expected.txt) events as the Python reference"
else
  echo "FAIL: first differences:"; diff expected.txt got.txt | head -20; exit 1
fi

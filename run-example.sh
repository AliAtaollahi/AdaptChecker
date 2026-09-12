#!/bin/sh
# The case study of Section 4: the heater model and the revision that adds a
# Notifyer rebec.  Writes both RDGs and the verdict into ./out.
set -e
cd "$(dirname "$0")"
python3 adaptcheck.py examples/1-heater.rebeca examples/2-heater.rebeca \
        examples/heater-observable.txt -o out "$@"

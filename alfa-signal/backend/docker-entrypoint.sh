#!/bin/sh
set -eu

python scripts/seed_demo.py

exec "$@"

#!/bin/sh
# Демонстрация версии 3: три независимых процесса (запускать из корня проекта)
BASE=${1:-/garden_demo}
./garden_init -n "$BASE" -W 10 -H 6 -p 0 -t 80,80 -k 150,150 -v 1 &
INIT=$!
sleep 0.5
./gardener1 -n "$BASE" > /dev/null &
./gardener2 -n "$BASE" > /dev/null &
wait $INIT
wait

#!/bin/sh
# Демонстрация версии 4: сервер сада и два садовника обмениваются сообщениями (из корня проекта)
BASE=${1:-/garden_demo_mq}
./garden_server -n "$BASE" -W 10 -H 6 -p 0 -t 80,80 -k 150,150 -v 1 &
SRV=$!
sleep 0.5
./gardener_mq1 -n "$BASE" > /dev/null &
./gardener_mq2 -n "$BASE" > /dev/null &
wait $SRV
wait

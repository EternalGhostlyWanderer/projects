#!/bin/sh
# Формирует файлы с примерами работы программы для раздела «Результаты» отчёта.
# Запускать из корня проекта после make:   sh tests/make_report_examples.sh
# Результаты сохраняются в test-results/examples/*.txt — их фрагменты можно вставлять в отчёт.
set -u
OUT="test-results/examples"
mkdir -p "$OUT"

run() {   # имя команда...
    name="$1"
    shift
    printf '$ %s\n' "$*" > "$OUT/$name.txt"
    "$@" >> "$OUT/$name.txt" 2>&1
    printf '\n[код завершения: %s]\n' "$?" >> "$OUT/$name.txt"
    echo "создан $OUT/$name.txt"
}

# 1. Обычный запуск небольшого сада, карта после каждой обработки
run 01_normal ./garden_named -W 6 -H 3 -p 15 -r 5 -t 20,20 -k 40,40 -v 1 -l "$OUT/01_normal.log"
# 2. Режим -v 2: карта после каждого перехода (положение садовников)
run 02_positions ./garden_named -W 4 -H 2 -p 0 -t 10,10 -k 10,10 -v 2 -l "$OUT/02_positions.log"
# 3. Ожидание занятой клетки (без обхода) и обход (с -o)
run 03_wait ./garden_named -W 4 -H 4 -p 0 -A TL:rows -B BR:cols -t 30,30 -k 5,5 -v 0 -l "$OUT/03_wait.log"
run 04_bypass ./garden_named -W 4 -H 4 -p 0 -A TL:rows -B BR:cols -t 30,30 -k 5,5 -o -v 0 -l "$OUT/04_bypass.log"
# 4. Карта с препятствиями и прудами (пропуск препятствий)
run 05_ponds ./garden_named -m tests/map_ponds.txt -t 10,10 -k 10,10 -v 0 -l "$OUT/05_ponds.log"
# 5. Изолированные клетки: завершение с диагностикой координат
run 06_unreachable ./garden_named -m tests/map_center_island.txt -t 5,5 -k 5,5 -v 0 -l "$OUT/06_unreachable.log"
# 6. Тупик: встречные садовники в коридоре (код 2)
run 07_deadlock ./garden_named -W 5 -H 1 -p 0 -a 1,5 -b 1,1 -t 10,10 -k 10,10 -v 0 -l "$OUT/07_deadlock.log"
# 7. Вторая реализация синхронизации
run 08_cv ./garden_unnamed -W 6 -H 3 -p 15 -r 5 -t 20,20 -k 40,40 -v 0 -l "$OUT/08_cv.log"
# 8. Прерывание сигналом SIGINT (код 3)
printf '$ ./garden_named -W 8 -H 6 -p 0 -t 100,100 -k 1000,1000 -v 0   (SIGINT через 0.5 с)\n' > "$OUT/09_sigint.txt"
./garden_named -W 8 -H 6 -p 0 -t 100,100 -k 1000,1000 -v 0 -l "$OUT/09_sigint.log" >> "$OUT/09_sigint.txt" 2>&1 &
pid=$!
sleep 0.5
kill -INT "$pid" 2>/dev/null
wait "$pid"
printf '\n[код завершения: %s]\n' "$?" >> "$OUT/09_sigint.txt"
echo "создан $OUT/09_sigint.txt"
echo "Готово. Вставьте нужные фрагменты в раздел отчёта «Результаты работы»."

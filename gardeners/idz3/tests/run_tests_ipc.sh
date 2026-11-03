#!/bin/sh
# Тесты версий с процессами: fork (garden_named, garden_unnamed — проверяются в run_tests.sh),
# независимые процессы (garden_init + gardener1/2) и очередь сообщений
# (garden_server + gardener_mq1/2). Проверяются результат, журнал, сигналы,
# аварийная гибель процесса и удаление объектов IPC (shm, семафоры, очереди).
# Запуск из корня проекта: make test
set -u
RESULT_DIR="test-results/ipc"
mkdir -p "$RESULT_DIR"
rm -f "$RESULT_DIR"/* 2>/dev/null
passed=0
failed=0
cc -o "$RESULT_DIR/ipcprobe" tests/ipcprobe.c -lrt -pthread 2>/dev/null || { echo "Не удалось собрать ipcprobe"; exit 1; }
PROBE="$RESULT_DIR/ipcprobe"

pass() { printf 'PASS: %s\n' "$1"; passed=$((passed + 1)); }
fail() { printf 'FAIL: %s\n' "$1"; printf 'FAIL: %s\n' "$1" >> "$RESULT_DIR/failures.txt"; failed=$((failed + 1)); }
check() { # check ИМЯ ОЖИДАЕМОЕ ФАКТИЧЕСКОЕ
    if [ "$2" = "$3" ]; then pass "$1 ($3)"; else fail "$1: ожидалось '$2', получено '$3'"; fi
}
has() { # has ИМЯ ФАЙЛ ТЕКСТ
    if grep -q -- "$3" "$2"; then pass "$1"; else fail "$1: в $2 нет '$3'"; fi
}
no_ipc_left() { # no_ipc_left ИМЯ БАЗА
    if out=$("$PROBE" "$2" 2>&1); then pass "$1: объекты IPC удалены"; else fail "$1: остались объекты IPC: $out"; fi
}

# Независимые процессы: garden_init, затем gardener1 и gardener2 отдельными запусками.
# Результат: IND_RC (код garden_init), вывод в $RESULT_DIR/$1.out, журнал $1.log
run_ind() {
    name=$1; base=$2; shift 2
    timeout 120 ./garden_init -n "$base" -l "$RESULT_DIR/$name.log" "$@" > "$RESULT_DIR/$name.out" 2>&1 &
    ip=$!
    sleep 0.3
    ./gardener1 -n "$base" > "$RESULT_DIR/$name.g1.out" 2>&1 &
    ./gardener2 -n "$base" > "$RESULT_DIR/$name.g2.out" 2>&1 &
    wait $ip; IND_RC=$?
    wait
}
# Очередь сообщений: garden_server + gardener_mq1/2. Результат: MQ_RC
run_mq() {
    name=$1; base=$2; shift 2
    timeout 120 ./garden_server -n "$base" -l "$RESULT_DIR/$name.log" "$@" > "$RESULT_DIR/$name.out" 2>&1 &
    sp=$!
    sleep 0.3
    ./gardener_mq1 -n "$base" > "$RESULT_DIR/$name.g1.out" 2>&1 &
    ./gardener_mq2 -n "$base" > "$RESULT_DIR/$name.g2.out" 2>&1 &
    wait $sp; MQ_RC=$?
    wait
}
done_line() { grep -m1 'Обработано клеток' "$1" | sed 's/;.*//'; }

printf '=== Независимые процессы и очередь сообщений: те же результаты, что у fork-версии ===\n'
n=0
for m in islands corridor vertical_wall center_island route_independence ponds obstacle_custom_start; do
    n=$((n + 1))
    map="tests/map_$m.txt"
    ./garden_named -n "/gt_ref$n" -m "$map" -t 5,5 -k 5,5 -v 0 -l "$RESULT_DIR/ref_$m.log" > "$RESULT_DIR/ref_$m.out" 2>&1
    ref_rc=$?
    ref_done=$(done_line "$RESULT_DIR/ref_$m.out")
    run_ind "ind_$m" "/gt_i$n" -m "$map" -t 5,5 -k 5,5 -v 0
    check "garden_init $m: код завершения как у fork-версии" "$ref_rc" "$IND_RC"
    if [ "$ref_rc" -eq 0 ]; then
        check "garden_init $m: число обработанных клеток" "$ref_done" "$(done_line "$RESULT_DIR/ind_$m.out")"
        if sh tests/check_log.sh "$RESULT_DIR/ind_$m.log" > "$RESULT_DIR/ind_$m.check" 2>&1; then
            pass "garden_init $m: независимая проверка журнала"
        else fail "garden_init $m: журнал нарушает инварианты (см. $RESULT_DIR/ind_$m.check)"; fi
    fi
    no_ipc_left "garden_init $m" "/gt_i$n"
    run_mq "mq_$m" "/gt_q$n" -m "$map" -t 5,5 -k 5,5 -v 0
    check "garden_server $m: код завершения как у fork-версии" "$ref_rc" "$MQ_RC"
    if [ "$ref_rc" -eq 0 ]; then
        check "garden_server $m: число обработанных клеток" "$ref_done" "$(done_line "$RESULT_DIR/mq_$m.out")"
        if sh tests/check_log.sh "$RESULT_DIR/mq_$m.log" > "$RESULT_DIR/mq_$m.check" 2>&1; then
            pass "garden_server $m: независимая проверка журнала"
        else fail "garden_server $m: журнал нарушает инварианты (см. $RESULT_DIR/mq_$m.check)"; fi
    fi
    no_ipc_left "garden_server $m" "/gt_q$n"
done

printf '\n=== Обход занятой клетки (-o) и режимы карты ===\n'
run_ind ind_bypass /gt_b1 -W 8 -H 6 -p 10 -r 11 -t 10,10 -k 10,10 -o -v 1
check "garden_init -o: код" 0 "$IND_RC"
has "garden_init -o: итог в выводе" "$RESULT_DIR/ind_bypass.out" "все достижимые клетки обработаны"
has "garden_init -v 1: карта после обработки (в общем журнале)" "$RESULT_DIR/ind_bypass.log" "клетка обработана"
run_mq mq_bypass /gt_b2 -W 8 -H 6 -p 10 -r 11 -t 10,10 -k 10,10 -o -v 2
check "garden_server -o -v 2: код" 0 "$MQ_RC"
has "garden_server -v 2: карта после перехода" "$RESULT_DIR/mq_bypass.out" "после перехода"
has "garden_server: события садовников" "$RESULT_DIR/mq_bypass.out" "начал обработку клетки"
has "garden_server: прибытие" "$RESULT_DIR/mq_bypass.out" "прибыл в"

printf '\n=== Порядок запуска: садовники стартуют раньше garden_init ===\n'
./gardener1 -n /gt_o1 > "$RESULT_DIR/order.g1.out" 2>&1 &
./gardener2 -n /gt_o1 > "$RESULT_DIR/order.g2.out" 2>&1 &
sleep 0.5
timeout 60 ./garden_init -n /gt_o1 -W 5 -H 3 -p 10 -r 2 -t 5,5 -k 5,5 -v 0 -l "$RESULT_DIR/order.log" > "$RESULT_DIR/order.out" 2>&1
check "садовники запущены до garden_init: код" 0 "$?"
wait
no_ipc_left "порядок запуска" "/gt_o1"
./gardener_mq1 -n /gt_o2 > /dev/null 2>&1 &
./gardener_mq2 -n /gt_o2 > /dev/null 2>&1 &
sleep 0.5
timeout 60 ./garden_server -n /gt_o2 -W 5 -H 3 -p 10 -r 2 -t 5,5 -k 5,5 -v 0 -l "$RESULT_DIR/order_mq.log" > "$RESULT_DIR/order_mq.out" 2>&1
check "садовники запущены до garden_server: код" 0 "$?"
wait
no_ipc_left "порядок запуска (очереди)" "/gt_o2"

printf '\n=== Одновременные независимые запуски с разными именами ===\n'
timeout 60 ./garden_init -n /gt_p1 -W 6 -H 4 -r 1 -t 10,10 -k 10,10 -v 0 -l "$RESULT_DIR/par1.log" > "$RESULT_DIR/par1.out" 2>&1 &
p1=$!
timeout 60 ./garden_init -n /gt_p2 -W 6 -H 4 -r 2 -t 10,10 -k 10,10 -v 0 -l "$RESULT_DIR/par2.log" > "$RESULT_DIR/par2.out" 2>&1 &
p2=$!
sleep 0.3
for b in /gt_p1 /gt_p2; do ./gardener1 -n $b > /dev/null 2>&1 & ./gardener2 -n $b > /dev/null 2>&1 & done
wait $p1; check "параллельный запуск 1: код" 0 "$?"
wait $p2; check "параллельный запуск 2: код" 0 "$?"
wait
no_ipc_left "параллельный запуск 1" "/gt_p1"
no_ipc_left "параллельный запуск 2" "/gt_p2"

printf '\n=== Сигналы и аварийное завершение ===\n'
for variant in init server; do
    if [ "$variant" = init ]; then srv=./garden_init; g1=./gardener1; g2=./gardener2; pre=gt_s
    else srv=./garden_server; g1=./gardener_mq1; g2=./gardener_mq2; pre=gt_m; fi
    # SIGINT процессу-координатору
    base="/${pre}1"
    $srv -n $base -W 20 -H 10 -p 5 -r 1 -t 100,100 -k 200,200 -v 0 -l "$RESULT_DIR/sig_$variant.log" > "$RESULT_DIR/sig_$variant.out" 2>&1 &
    sp=$!; sleep 0.3
    $g1 -n $base > /dev/null 2>&1 & $g2 -n $base > /dev/null 2>&1 &
    sleep 1; kill -INT $sp; wait $sp; check "$variant: SIGINT координатору — код" 3 "$?"; wait
    has "$variant: SIGINT — причина в итоге" "$RESULT_DIR/sig_$variant.out" "прервано сигналом"
    has "$variant: SIGINT — садовники остановлены" "$RESULT_DIR/sig_$variant.out" "прерван сигналом"
    no_ipc_left "$variant: после SIGINT" "$base"
    # SIGINT только садовнику: останавливаются все
    base="/${pre}2"
    $srv -n $base -W 20 -H 10 -p 5 -r 1 -t 100,100 -k 200,200 -v 0 -l "$RESULT_DIR/sigg_$variant.log" > "$RESULT_DIR/sigg_$variant.out" 2>&1 &
    sp=$!; sleep 0.3
    $g1 -n $base > /dev/null 2>&1 & gp=$!
    $g2 -n $base > /dev/null 2>&1 &
    sleep 1; kill -INT $gp; wait $sp; check "$variant: SIGINT садовнику — код" 3 "$?"; wait
    no_ipc_left "$variant: после SIGINT садовнику" "$base"
    # SIGTERM координатору
    base="/${pre}3"
    $srv -n $base -W 20 -H 10 -p 5 -r 1 -t 100,100 -k 200,200 -v 0 -l "$RESULT_DIR/term_$variant.log" > "$RESULT_DIR/term_$variant.out" 2>&1 &
    sp=$!; sleep 0.3
    $g1 -n $base > /dev/null 2>&1 & $g2 -n $base > /dev/null 2>&1 &
    sleep 1; kill -TERM $sp; wait $sp; check "$variant: SIGTERM — код" 3 "$?"; wait
    no_ipc_left "$variant: после SIGTERM" "$base"
    # Повторный сигнал: немедленный выход, объекты IPC удалены
    base="/${pre}4"
    $srv -n $base -W 30 -H 20 -p 5 -r 1 -t 300,300 -k 500,500 -v 0 -l "$RESULT_DIR/twice_$variant.log" > "$RESULT_DIR/twice_$variant.out" 2>&1 &
    sp=$!; sleep 0.3
    $g1 -n $base > /dev/null 2>&1 & $g2 -n $base > /dev/null 2>&1 &
    sleep 1; kill -INT $sp; sleep 0.05; kill -INT $sp; wait $sp; rc=$?
    if [ "$rc" -eq 3 ] || [ "$rc" -eq 130 ]; then pass "$variant: повторный SIGINT — код ($rc)"; else fail "$variant: повторный SIGINT: код $rc"; fi
    wait
    sleep 0.3
    no_ipc_left "$variant: после повторного SIGINT" "$base"
    # kill -9 одному из садовников
    base="/${pre}5"
    $srv -n $base -W 20 -H 10 -p 5 -r 1 -t 100,100 -k 200,200 -v 0 -l "$RESULT_DIR/kill_$variant.log" > "$RESULT_DIR/kill_$variant.out" 2>&1 &
    sp=$!; sleep 0.3
    $g1 -n $base > /dev/null 2>&1 &
    $g2 -n $base > /dev/null 2>&1 & kp=$!
    sleep 1; kill -KILL $kp; wait $sp; check "$variant: гибель садовника — код" 2 "$?"; wait 2>/dev/null
    has "$variant: гибель садовника — сообщение" "$RESULT_DIR/kill_$variant.out" "ОШИБКА: процесс садовника 2"
    has "$variant: гибель садовника — причина" "$RESULT_DIR/kill_$variant.out" "аварийно завершился процесс садовника"
    no_ipc_left "$variant: после kill -9 садовника" "$base"
done

printf '\n=== Справка и ошибки параметров ===\n'
for prog in garden_init garden_server; do
    ./$prog -h > "$RESULT_DIR/h_$prog.out" 2>&1; check "$prog -h: код" 0 "$?"
    has "$prog -h: описан параметр -n" "$RESULT_DIR/h_$prog.out" "-n ИМЯ"
    ./$prog -W 0 > /dev/null 2>&1; check "$prog: неверная ширина — код" 1 "$?"
    ./$prog -m tests/map_obstacle_at_start.txt > /dev/null 2>&1; check "$prog: препятствие на старте — код" 1 "$?"
    no_ipc_left "$prog: ошибка параметров не оставляет объектов" "/garden_$$"
done
for prog in gardener1 gardener2 gardener_mq1 gardener_mq2; do
    ./$prog -h > /dev/null 2>&1; check "$prog -h: код" 0 "$?"
done

printf '\n================ ИТОГ ТЕСТОВ ПРОЦЕССОВ ================\n'
printf 'Успешно: %d\nОшибок:   %d\n' "$passed" "$failed"
[ "$failed" -eq 0 ]

#!/bin/sh
# Набор автоматических интеграционных тестов для garden_sem и garden_cv.
# Запускать из корня проекта командой: make test
set -u

RESULT_DIR="test-results"
mkdir -p "$RESULT_DIR"
# Прошлые результаты удаляем (каталог examples с примерами для отчёта сохраняется)
find "$RESULT_DIR" -mindepth 1 -maxdepth 1 ! -name examples -exec rm -rf {} + 2>/dev/null
passed=0
failed=0
skipped=0

# FIFO создаём во временном каталоге Linux: на диске Windows (/mnt/c в WSL) FIFO не работают
FIFO_DIR=$(mktemp -d 2>/dev/null || echo "")
make_fifo() {
    fifo="$FIFO_DIR/dialog.fifo"
    rm -f "$fifo"
    if [ -n "$FIFO_DIR" ] && mkfifo "$fifo" 2>/dev/null && [ -p "$fifo" ]; then
        return 0
    fi
    printf 'SKIP: FIFO недоступен в этой файловой системе — проверка пропущена\n'
    skipped=$((skipped + 1))
    return 1
}

pass() {
    printf 'PASS: %s\n' "$1"
    passed=$((passed + 1))
}

fail() {
    printf 'FAIL: %s\n' "$1"
    printf 'FAIL: %s\n' "$1" >> "$RESULT_DIR/failures.txt"
    failed=$((failed + 1))
}

# Запускает команду и возвращает её вывод в TEST_OUTPUT и код в TEST_RC.
run_capture() {
    if TEST_OUTPUT=$("$@" 2>&1); then
        TEST_RC=0
    else
        TEST_RC=$?
    fi
}

expect_exit() {
    name="$1"
    expected="$2"
    shift 2
    run_capture "$@"
    if [ "$TEST_RC" -eq "$expected" ]; then
        pass "$name (код $expected)"
    else
        printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
        fail "$name: ожидался код $expected, получен $TEST_RC"
    fi
}

expect_exit_either() {
    name="$1"
    first="$2"
    second="$3"
    shift 3
    run_capture "$@"
    if [ "$TEST_RC" -eq "$first" ] || [ "$TEST_RC" -eq "$second" ]; then
        pass "$name (код $TEST_RC)"
    else
        printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
        fail "$name: ожидался код $first или $second, получен $TEST_RC"
    fi
}

expect_text() {
    name="$1"
    text="$2"
    if printf '%s\n' "$TEST_OUTPUT" | grep -Fq -- "$text"; then
        pass "$name"
    else
        printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
        fail "$name: не найден текст '$text'"
    fi
}

# ---------------------------------------------------------------------
# Дополнительные помощники
# ---------------------------------------------------------------------

# expect_no_text имя текст — в TEST_OUTPUT нет указанного текста
expect_no_text() {
    name="$1"
    text="$2"
    if printf '%s\n' "$TEST_OUTPUT" | grep -Fq -- "$text"; then
        printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
        fail "$name: найден лишний текст '$text'"
    else
        pass "$name"
    fi
}

# expect_rc имя ожидаемый_код фактический_код
expect_rc() {
    if [ "$3" -eq "$2" ] 2>/dev/null; then
        pass "$1 (код $2)"
    else
        fail "$1: ожидался код $2, получен $3"
    fi
}

# expect_count имя ожидаемое_число фактическое_число
expect_count() {
    if [ "$3" -eq "$2" ] 2>/dev/null; then
        pass "$1 ($2)"
    else
        fail "$1: ожидалось $2, получено $3"
    fi
}

# expect_rc_either имя код1 код2 фактический_код
expect_rc_either() {
    if [ "$4" -eq "$2" ] 2>/dev/null || [ "$4" -eq "$3" ] 2>/dev/null; then
        pass "$1 (код $4)"
    else
        fail "$1: ожидался код $2 или $3, получен $4"
    fi
}

# file_has имя файл текст / file_lacks имя файл текст
file_has() {
    if grep -Fq -- "$3" "$2"; then
        pass "$1"
    else
        fail "$1: в $2 не найден текст '$3'"
    fi
}

file_lacks() {
    if grep -Fq -- "$3" "$2"; then
        fail "$1: в $2 найден лишний текст '$3'"
    else
        pass "$1"
    fi
}

# Независимая проверка журнала по событиям (tests/check_log.sh):
# нет двух садовников в одной клетке, препятствия не посещаются и не
# обрабатываются, клетка обрабатывается не более одного раза.
check_log() {
    if clog_out=$(sh tests/check_log.sh "$2" 2>&1); then
        pass "$1: журнал соответствует инвариантам"
    else
        printf '%s\n' "$clog_out" > "$RESULT_DIR/failed_${failed}.txt"
        fail "$1: $clog_out"
    fi
}

# Запуск с выводом (stdout+stderr) в файл; код возврата в RUN_RC.
run_to_file() {
    rtf_out="$1"
    shift
    if "$@" > "$rtf_out" 2>&1; then
        RUN_RC=0
    else
        RUN_RC=$?
    fi
}

# Ожидание фонового процесса не дольше N секунд. Код возврата — в WAIT_RC
# (137 означает, что процесс завис и был убит).
wait_timeout() {
    wt_pid="$1"
    wt_secs="$2"
    ( sleep "$wt_secs"; kill -9 "$wt_pid" 2>/dev/null ) > /dev/null 2>&1 &
    wt_guard=$!
    if wait "$wt_pid"; then
        WAIT_RC=0
    else
        WAIT_RC=$?
    fi
    kill "$wt_guard" 2>/dev/null
    wait "$wt_guard" 2>/dev/null || true
}

# extract_grid файл метка число_строк — строки карты, следующие за заголовком
# с указанной меткой, без пробелов (например, "1../..2").
extract_grid() {
    awk -v marker="$2" -v n="$3" '
        index($0, marker) { capture = 1; next }
        capture && /^    [.#~+12 ]+$/ {
            line = $0
            sub(/^    /, "", line)
            gsub(/ /, "", line)
            print line
            rows++
            if (rows == n) exit
        }
    ' "$1"
}

# processed_sequence файл номер_садовника — клетки в порядке начала обработки
# («1,1 1,2 ... » с завершающим пробелом).
processed_sequence() {
    grep -F "Садовник $2: начал обработку клетки" "$1" |
        sed 's/.*клетки (\([0-9][0-9]*,[0-9][0-9]*\)).*/\1/' | tr '\n' ' '
}

# Прогон сценария с взаимодействием потоков и проверкой инвариантов:
# run_interaction_case имя программа аргументы...
ric_counter=0
run_interaction_case() {
    ric_name="$1"
    ric_prog="$2"
    shift 2
    ric_counter=$((ric_counter + 1))
    ric_log="$RESULT_DIR/interaction_${ric_counter}.log"
    run_to_file "$RESULT_DIR/interaction_${ric_counter}.out" "./$ric_prog" "$@" -l "$ric_log"
    expect_rc_either "$ric_name" 0 2 "$RUN_RC"
    file_has "$ric_name: встроенный контроль инвариантов без нарушений" "$ric_log" "нарушений: 0"
    file_lacks "$ric_name: нет сообщения о нарушении инварианта" "$ric_log" "НАРУШЕНИЕ ИНВАРИАНТА"
    check_log "$ric_name" "$ric_log"
}

printf '\n=== Проверка справки и командной строки ===\n'
expect_exit "garden_sem выводит справку" 0 ./garden_sem -h
run_capture ./garden_sem -h
if printf '%s\n' "$TEST_OUTPUT" | grep -Fq 'Использование:'; then
    pass "справка содержит инструкцию запуска"
else
    fail "справка содержит инструкцию запуска"
fi
expect_exit "отклоняет нулевую ширину" 1 ./garden_sem -W 0
expect_exit "отклоняет высоту больше максимума" 1 ./garden_sem -H 41
expect_exit "отклоняет долю препятствий больше 90%" 1 ./garden_sem -p 101
expect_exit "отклоняет некорректное время перехода" 1 ./garden_sem -t bad,10
expect_exit "отклоняет некорректный маршрут" 1 ./garden_sem -A WRONG
expect_exit "отклоняет одинаковые стартовые клетки" 1 ./garden_sem -W 3 -H 3 -p 0 -a 1,1 -b 1,1

printf '\n=== Успешная обработка сада ===\n'
expect_exit "реализация с семафорами: сад 1x2 без препятствий" 0 \
    ./garden_sem -W 2 -H 1 -p 0 -r 123 -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/open_1x2_sem.log"
run_capture ./garden_sem -W 2 -H 1 -p 0 -r 123 -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/open_1x2_sem_check.log"
if printf '%s\n' "$TEST_OUTPUT" | grep -Fq 'Причина завершения: все достижимые клетки обработаны' &&
   printf '%s\n' "$TEST_OUTPUT" | grep -Fq 'Обработано клеток: 2 из 2'; then
    pass "малый сад обрабатывает обе клетки"
else
    fail "малый сад обрабатывает обе клетки"
fi

expect_exit "условные переменные: сад 1x2 без препятствий" 0 \
    ./garden_cv -W 2 -H 1 -p 0 -r 123 -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/open_1x2_cv.log"
expect_exit "маршрут по столбцам в garden_sem" 0 \
    ./garden_sem -W 5 -H 4 -p 0 -A TL:cols -B BR:cols -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/cols_sem.log"
expect_exit "маршрут по столбцам в garden_cv" 0 \
    ./garden_cv -W 5 -H 4 -p 0 -A TL:cols -B BR:cols -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/cols_cv.log"
expect_exit "режим карты после каждого перехода" 0 \
    ./garden_sem -W 3 -H 2 -p 0 -t 0,0 -k 0,0 -o -v 2 -l "$RESULT_DIR/view2.log"
run_capture ./garden_sem -W 3 -H 2 -p 0 -t 0,0 -k 0,0 -o -v 2 -l "$RESULT_DIR/view2_check.log"
expect_text "при подробном выводе карта перерисовывается после перехода" "после перехода"

printf '\n=== Карты и препятствия ===\n'
expect_exit_either "карта с несколькими препятствиями загружается" 0 2 \
    ./garden_sem -m tests/map_islands.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/map_islands.log"
run_capture ./garden_sem -m tests/map_islands.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/map_events.log"
expect_text "препятствия явно пропускаются в журнале" "пропускает недоступную клетку"
expect_text "в конце печатается статистика" "Обработано клеток:"

expect_exit_either "карта с вертикальной стеной обрабатывается" 0 2 \
    ./garden_cv -m tests/map_vertical_wall.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/vertical_wall.log"
expect_exit_either "узкий коридор обрабатывается без зависания" 0 2 \
    ./garden_sem -m tests/map_corridor.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/corridor.log"

run_capture ./garden_sem -m tests/map_center_island.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/center_island.log"
if [ "$TEST_RC" -eq 0 ] || [ "$TEST_RC" -eq 2 ]; then
    if printf '%s\n' "$TEST_OUTPUT" | grep -Fq 'Диагностика необработанных участков' &&
       printf '%s\n' "$TEST_OUTPUT" | grep -Fq 'недостижима: изолирована препятствиями'; then
        pass "изолированная клетка отражена в диагностике"
    else
        printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
        fail "изолированная клетка отражена в диагностике"
    fi
else
    printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
    fail "изолированная клетка: неожиданный код $TEST_RC"
fi

expect_exit "отклоняет карту с разной длиной строк" 1 \
    ./garden_sem -m tests/map_bad_rows.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/bad_rows.log"
expect_exit "отклоняет стартовую клетку-препятствие" 1 \
    ./garden_sem -m tests/map_obstacle_at_start.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/obstacle_start.log"
expect_exit "отклоняет карту без свободных стартовых клеток" 1 \
    ./garden_sem -m tests/map_no_free_area.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/no_free_area.log"
expect_exit "отклоняет несуществующий файл карты" 1 \
    ./garden_sem -m tests/does_not_exist.txt -t 0,0 -k 0,0 -o -v 0 -l "$RESULT_DIR/missing_map.log"

printf '\n=== Ожидание занятой клетки и обход ===\n'
# Разные маршруты на одной карте создают пересечения: это позволяет проверить
# события ожидания и разрешённого обхода, которые отдельно отмечены в условии.
run_capture ./garden_sem -W 4 -H 4 -p 0 -A TL:rows -B BR:cols \
    -t 30,30 -k 5,5 -v 0 -l "$RESULT_DIR/wait_event.log"
if { [ "$TEST_RC" -eq 0 ] || [ "$TEST_RC" -eq 2 ]; } &&
   printf '%s\n' "$TEST_OUTPUT" | grep -Fq 'ожидает освобождения'; then
    pass "без обхода выводится событие ожидания занятой клетки"
else
    printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
    fail "без обхода выводится событие ожидания занятой клетки"
fi

# Событие обхода зависит от реального чередования потоков, поэтому запускаем
# один и тот же сценарий несколько раз и требуем хотя бы одно наблюдение обхода.
for program in garden_sem garden_cv; do
    bypass_seen=0
    attempt=1
    while [ "$attempt" -le 5 ] && [ "$bypass_seen" -eq 0 ]; do
        run_capture "./$program" -W 4 -H 4 -p 0 -A TL:rows -B BR:cols \
            -t 30,30 -k 5,5 -o -v 0 -l "$RESULT_DIR/${program}_bypass_${attempt}.log"
        printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/${program}_bypass_${attempt}.out"
        if { [ "$TEST_RC" -eq 0 ] || [ "$TEST_RC" -eq 2 ]; } && \
           printf '%s\n' "$TEST_OUTPUT" | grep -Fq 'обходит через'; then
            bypass_seen=1
        fi
        attempt=$((attempt + 1))
    done
    if [ "$bypass_seen" -eq 1 ]; then
        pass "$program поддерживает обход занятой клетки"
    else
        cp "$RESULT_DIR/${program}_bypass_5.out" "$RESULT_DIR/failed_${failed}.txt"
        fail "$program поддерживает обход занятой клетки"
    fi
done

printf '\n=== Контроль инвариантов и независимость от маршрутов ===\n'
# На одной и той же карте с двумя изолированными зонами меняем стратегию обхода.
# В каждой зоне работает один садовник, поэтому тест сравнивает именно порядок
# обхода, не создавая отдельного сценария взаимной блокировки.
extract_final_grid() {
    awk '
        /-- итоговое состояние сада/ { capture = 1; next }
        capture && /^    [.#~+12 ]+$/ {
            line = $0
            sub(/^    /, "", line)
            gsub(/ /, "", line)
            print line
            rows++
            if (rows == 4) exit
        }
    ' "$1"
}

reference_grid=""
independence_failed=0
case_number=0
for program in garden_sem garden_cv; do
    for routes in "TL:rows BR:rows" "TL:cols BR:cols" "TL:rows BR:cols" "TL:cols BR:rows"; do
        set -- $routes
        route_a="$1"
        route_b="$2"
        case_number=$((case_number + 1))
        output_file="$RESULT_DIR/route_independence_${case_number}.out"
        log_file="$RESULT_DIR/route_independence_${case_number}.log"

        if "./$program" -m tests/map_route_independence.txt \
            -A "$route_a" -B "$route_b" -t 0,0 -k 0,0 -o -v 0 \
            -l "$log_file" > "$output_file" 2>&1; then
            route_rc=0
        else
            route_rc=$?
        fi

        grid="$(extract_final_grid "$output_file")"
        if [ "$route_rc" -ne 0 ] || \
           ! grep -Fq 'Обработано клеток: 16 из 16 доступных' "$output_file" || \
           [ "$(printf '%s\n' "$grid" | wc -l | tr -d ' ')" -ne 4 ]; then
            printf 'FAIL: %s, маршруты %s / %s, код %s\n' \
                "$program" "$route_a" "$route_b" "$route_rc"
            fail "$program: результат обработан не полностью для маршрутов $route_a / $route_b"
            independence_failed=1
            continue
        fi

        if [ -z "$reference_grid" ]; then
            reference_grid="$grid"
            pass "опорное итоговое состояние сохранено ($program, $route_a / $route_b)"
        elif [ "$grid" = "$reference_grid" ]; then
            pass "$program: итоговое состояние не зависит от маршрутов $route_a / $route_b"
        else
            printf 'FAIL: разные финальные карты для %s (%s / %s)\n' \
                "$program" "$route_a" "$route_b"
            printf 'Эталон:\n%s\nПолучено:\n%s\n' "$reference_grid" "$grid"
            fail "$program: независимость итогового состояния от маршрутов"
            independence_failed=1
        fi

        if ! grep -Fq 'Проверки инвариантов:' "$output_file" || \
           ! grep -Fq 'нарушений: 0' "$output_file"; then
            fail "$program: в сценарии маршрутов нарушен инвариант"
            independence_failed=1
        else
            pass "$program: контроль инвариантов завершился без нарушений"
        fi
    done
done

if [ "$independence_failed" -ne 0 ]; then
    printf 'Некоторые проверки независимости или инвариантов завершились с ошибкой.\n'
fi

printf '\n=== Прерывание сигналом ===\n'
for program in garden_sem garden_cv; do
    log="$RESULT_DIR/${program}_signal.log"
    output="$RESULT_DIR/${program}_signal.out"
    "./$program" -W 8 -H 6 -p 0 -t 100,100 -k 1000,1000 -o -v 0 -l "$log" > "$output" 2>&1 &
    pid=$!
    sleep 0.15
    if kill -0 "$pid" 2>/dev/null; then
        kill -INT "$pid" 2>/dev/null || true
        if wait "$pid"; then
            rc=0
        else
            rc=$?
        fi
        if [ "$rc" -eq 3 ] && grep -Fq 'прервано сигналом' "$output"; then
            pass "$program корректно обрабатывает SIGINT"
        else
            fail "$program: SIGINT, код $rc (ожидался 3)"
        fi
    else
        wait "$pid" || true
        fail "$program завершился до отправки SIGINT"
    fi
done

printf '\n=== Расширенная проверка параметров (код 1) ===\n'
expect_exit "ширина больше 60" 1 ./garden_sem -W 61
expect_exit "высота 0" 1 ./garden_sem -H 0
expect_exit "отрицательная доля препятствий" 1 ./garden_sem -p -1
expect_exit "нечисловое зерно" 1 ./garden_sem -r abc
expect_exit "режим вывода 3" 1 ./garden_sem -v 3
expect_exit "-a без запятой" 1 ./garden_sem -a 1
expect_exit "-b с нечисловым значением" 1 ./garden_sem -b x,y
expect_exit "старт садовника 1: строка вне сада" 1 ./garden_sem -W 3 -H 3 -p 0 -a 4,1
expect_exit "старт садовника 2: столбец вне сада" 1 ./garden_sem -W 3 -H 3 -p 0 -b 1,4
expect_exit "старт садовника 1: нулевая строка" 1 ./garden_sem -W 3 -H 3 -p 0 -a 0,1
expect_exit "отрицательное время перехода" 1 ./garden_sem -t -5,1
expect_exit "три значения времени перехода" 1 ./garden_sem -t 1,2,3
expect_exit "нечисловое время обработки" 1 ./garden_sem -k x
expect_exit "время перехода выше лимита" 1 ./garden_sem -t 100001,1
expect_exit "неверный маршрут садовника 2" 1 ./garden_sem -B ZZ
expect_exit "неверный суффикс маршрута" 1 ./garden_sem -A TL:diag
expect_exit "неизвестный параметр" 1 ./garden_sem -z
expect_exit "параметр без аргумента" 1 ./garden_sem -W
expect_exit "лишний позиционный аргумент" 1 ./garden_sem extra
expect_exit "garden_cv: ширина 0" 1 ./garden_cv -W 0
expect_exit "garden_cv: неверный маршрут" 1 ./garden_cv -B ZZ
expect_exit "garden_cv: одинаковые старты" 1 ./garden_cv -W 3 -H 3 -p 0 -a 2,2 -b 2,2
expect_exit "garden_cv выводит справку" 0 ./garden_cv -h
expect_exit "старт садовника 1 на препятствии" 1 \
    ./garden_sem -m tests/map_obstacle_custom_start.txt -a 2,2 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/custom_obstacle_a.log"
expect_text "сообщение о недоступной стартовой клетке" "недоступна"
expect_exit "старт садовника 2 на препятствии" 1 \
    ./garden_sem -m tests/map_obstacle_custom_start.txt -b 2,2 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/custom_obstacle_b.log"
run_capture ./garden_sem -m tests/map_route_independence.txt -W 9 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/map_with_w.log"
expect_text "-W при -m: предупреждение, а не молчаливое игнорирование" "Предупреждение: -W, -H, -p и -r не действуют"
expect_rc "-W при -m: работа продолжается" 0 "$TEST_RC"

printf '\n=== Начальная карта: позиции садовников ===\n'
for program in garden_sem garden_cv; do
    f="$RESULT_DIR/${program}_initial_default.out"
    run_to_file "$f" "./$program" -W 3 -H 2 -p 0 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/${program}_initial_default.log"
    grid=$(extract_grid "$f" "начальное состояние сада" 2 | tr '\n' '/')
    if [ "$grid" = "1../..2/" ]; then
        pass "$program: на начальной карте садовники в углах (1,1) и (2,3)"
    else
        fail "$program: начальная карта по умолчанию: '$grid', ожидалось '1../..2/'"
    fi

    f="$RESULT_DIR/${program}_initial_custom.out"
    run_to_file "$f" "./$program" -W 5 -H 4 -p 0 -a 2,2 -b 3,4 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/${program}_initial_custom.log"
    grid=$(extract_grid "$f" "начальное состояние сада" 4 | tr '\n' '/')
    if [ "$grid" = "...../.1.../...2./...../" ]; then
        pass "$program: на начальной карте садовники в заданных клетках (2,2) и (3,4)"
    else
        fail "$program: начальная карта с -a/-b: '$grid'"
    fi
    expect_rc_either "$program: запуск с заданными стартами завершён" 0 2 "$RUN_RC"
    check_log "$program: заданные старты" "$RESULT_DIR/${program}_initial_custom.log"

    f="$RESULT_DIR/${program}_initial_corners.out"
    run_to_file "$f" "./$program" -W 4 -H 2 -p 0 -A TR:rows -B BL:rows -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/${program}_initial_corners.log"
    grid=$(extract_grid "$f" "начальное состояние сада" 2 | tr '\n' '/')
    if [ "$grid" = "...1/2.../" ]; then
        pass "$program: старты в углах маршрутов TR и BL"
    else
        fail "$program: начальная карта для TR/BL: '$grid'"
    fi
done

printf '\n=== События журнала (карта из двух изолированных зон) ===\n'
for program in garden_sem garden_cv; do
    f="$RESULT_DIR/${program}_events.out"
    log="$RESULT_DIR/${program}_events.log"
    run_to_file "$f" "./$program" -m tests/map_route_independence.txt -t 5,5 -k 5,5 -v 0 -l "$log"
    expect_rc "$program: карта с зонами" 0 "$RUN_RC"
    file_has "$program: старт садовника 1" "$f" "приступил к работе, стартовая клетка (1,1)"
    file_has "$program: старт садовника 2" "$f" "приступил к работе, стартовая клетка (4,5)"
    file_has "$program: событие перехода" "$f" "Садовник 1: переходит (1,1) -> (1,2)"
    file_has "$program: событие прибытия" "$f" "Садовник 1: прибыл в (1,2)"
    file_has "$program: начало обработки" "$f" "начал обработку клетки (1,1)"
    file_has "$program: окончание обработки" "$f" "закончил обработку клетки (1,1)"
    file_has "$program: пропуск препятствия" "$f" "пропускает недоступную клетку (1,3) [#]"
    file_has "$program: пропуск недостижимой клетки" "$f" "недостижима — пропуск"
    file_has "$program: освобождение клетки при завершении" "$f" "завершает работу (маршрут пройден), освобождает клетку"
    file_has "$program: итог — все достижимые обработаны" "$f" "Причина завершения: все достижимые клетки обработаны"
    file_has "$program: обработаны все 16 клеток" "$f" "Обработано клеток: 16 из 16 доступных"
    file_has "$program: проверки инвариантов выполнялись" "$f" "Проверки инвариантов:"
    file_has "$program: нарушений инвариантов нет" "$f" "нарушений: 0"
    count=$(grep -c "завершает работу" "$f")
    expect_count "$program: в журнале два сообщения о завершении садовников" 2 "$count"
    cmp -s "$f" "$log" && pass "$program: вывод на экран совпадает с журналом" || fail "$program: вывод на экран и журнал различаются"
    check_log "$program: карта с зонами" "$log"
done

printf '\n=== Порядок обхода змейкой (по журналу) ===\n'
# На карте с двумя зонами каждый садовник обрабатывает клетки только своей зоны,
# поэтому порядок его клеток однозначен и не зависит от расписания потоков.
for program in garden_sem garden_cv; do
    for a_route in "TL:rows" "TL:cols"; do
        for b_route in "BR:rows" "BR:cols"; do
            tag=$(printf '%s_%s_%s' "$program" "$a_route" "$b_route" | tr ':' '-')
            out="$RESULT_DIR/order_${tag}.out"
            run_to_file "$out" "./$program" -m tests/map_route_independence.txt -A "$a_route" -B "$b_route" -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/order_${tag}.log"
            expect_rc "$program: $a_route / $b_route завершается" 0 "$RUN_RC"
            case "$a_route" in
                TL:rows) expected1="1,1 1,2 2,2 2,1 3,1 3,2 4,2 4,1 " ;;
                *) expected1="1,1 2,1 3,1 4,1 4,2 3,2 2,2 1,2 " ;;
            esac
            case "$b_route" in
                BR:rows) expected2="4,5 4,4 3,4 3,5 2,5 2,4 1,4 1,5 " ;;
                *) expected2="4,5 3,5 2,5 1,5 1,4 2,4 3,4 4,4 " ;;
            esac
            seq1=$(processed_sequence "$out" 1)
            seq2=$(processed_sequence "$out" 2)
            if [ "$seq1" = "$expected1" ]; then
                pass "$program: порядок садовника 1 при $a_route"
            else
                fail "$program: порядок садовника 1 при $a_route: '$seq1', ожидалось '$expected1'"
            fi
            if [ "$seq2" = "$expected2" ]; then
                pass "$program: порядок садовника 2 при $b_route"
            else
                fail "$program: порядок садовника 2 при $b_route: '$seq2', ожидалось '$expected2'"
            fi
            check_log "$program: $a_route / $b_route" "$RESULT_DIR/order_${tag}.log"
        done
    done
done

printf '\n=== Тупик: встречные садовники в узком коридоре (код 2) ===\n'
for program in garden_sem garden_cv; do
    for width in 2 3 4 5 6; do
        for mode in "" "-o"; do
            mode_label=""
            [ -n "$mode" ] && mode_label=" $mode"
            tag="${program}_corridor_${width}${mode}"
            out="$RESULT_DIR/${tag}.out"
            log="$RESULT_DIR/${tag}.log"
            run_to_file "$out" "./$program" -W "$width" -H 1 -p 0 -a "1,$width" -b 1,1 -t 0,0 -k 0,0 -v 0 $mode -l "$log"
            expect_rc "$program: коридор $width$mode_label — тупик" 2 "$RUN_RC"
            file_has "$program: коридор $width$mode_label — сообщение ТУПИК" "$out" "ТУПИК"
            file_has "$program: коридор $width$mode_label — причина" "$out" "Причина завершения: тупик"
            file_has "$program: коридор $width$mode_label — диагностика" "$out" "Диагностика необработанных участков"
            file_has "$program: коридор $width$mode_label — координаты клеток" "$out" "достижима, но не обработана"
            file_has "$program: коридор $width$mode_label — нарушений инвариантов нет" "$out" "нарушений: 0"
            check_log "$program: коридор $width$mode_label" "$log"
        done
    done
done

printf '\n=== Взаимодействие потоков: инварианты при встрече садовников ===\n'
for program in garden_sem garden_cv; do
    run_interaction_case "$program: 4x4, пересекающиеся маршруты" "$program" -W 4 -H 4 -p 0 -A TL:rows -B BR:cols -t 30,30 -k 5,5 -v 0
    run_interaction_case "$program: 4x4, пересекающиеся маршруты, обход" "$program" -W 4 -H 4 -p 0 -A TL:rows -B BR:cols -t 30,30 -k 5,5 -o -v 0
    run_interaction_case "$program: 6x6 по умолчанию" "$program" -W 6 -H 6 -p 0 -t 2,2 -k 3,3 -v 0
    run_interaction_case "$program: 6x6 по умолчанию, обход" "$program" -W 6 -H 6 -p 0 -t 2,2 -k 3,3 -o -v 0
    run_interaction_case "$program: старты рядом" "$program" -W 6 -H 6 -p 0 -a 3,3 -b 3,4 -t 2,2 -k 3,3 -v 0
    run_interaction_case "$program: старты рядом, обход" "$program" -W 6 -H 6 -p 0 -a 3,3 -b 3,4 -t 2,2 -k 3,3 -o -v 0
    run_interaction_case "$program: разные скорости" "$program" -W 7 -H 5 -p 0 -t 1,8 -k 8,1 -o -v 0
    for seed in 1 2 3 4 5 6; do
        run_interaction_case "$program: случайный сад seed=$seed" "$program" -W 8 -H 6 -p 20 -r "$seed" -t 1,2 -k 2,1 -v 0
        run_interaction_case "$program: случайный сад seed=$seed, обход" "$program" -W 8 -H 6 -p 20 -r "$seed" -t 1,2 -k 2,1 -o -v 0
    done
    run_interaction_case "$program: острова" "$program" -m tests/map_islands.txt -t 2,2 -k 2,2 -v 0
    run_interaction_case "$program: центральный остров" "$program" -m tests/map_center_island.txt -t 2,2 -k 2,2 -v 0
done

printf '\n=== Недостижимые клетки: код 0 и диагностика с координатами ===\n'
for program in garden_sem garden_cv; do
    out="$RESULT_DIR/${program}_center_island.out"
    run_to_file "$out" "./$program" -m tests/map_center_island.txt -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/${program}_center_island2.log"
    expect_rc "$program: изолированные клетки не мешают завершению" 0 "$RUN_RC"
    file_has "$program: диагностика содержит клетку (2,4)" "$out" "(2,4) — недостижима: изолирована препятствиями"
    file_has "$program: причина завершения" "$out" "Причина завершения: все достижимые клетки обработаны"
done

printf '\n=== Генерация препятствий: доля и зерно ===\n'
f1="$RESULT_DIR/seed7_a.out"; f2="$RESULT_DIR/seed7_b.out"; f3="$RESULT_DIR/seed8.out"; f0="$RESULT_DIR/ratio0.out"
run_to_file "$f1" ./garden_sem -W 10 -H 6 -p 30 -r 7 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/seed7_a.log"
run_to_file "$f2" ./garden_cv -W 10 -H 6 -p 30 -r 7 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/seed7_b.log"
run_to_file "$f3" ./garden_sem -W 10 -H 6 -p 30 -r 8 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/seed8.log"
g1=$(extract_grid "$f1" "начальное состояние сада" 6)
g2=$(extract_grid "$f2" "начальное состояние сада" 6)
g3=$(extract_grid "$f3" "начальное состояние сада" 6)
if [ "$g1" = "$g2" ]; then pass "одно зерно даёт один и тот же сад в обеих сборках"; else fail "одно зерно дало разные сады"; fi
if [ "$g1" != "$g3" ]; then pass "разные зёрна дают разные сады"; else fail "зёрна 7 и 8 дали одинаковый сад"; fi
count=$(printf '%s\n' "$g1" | tr -cd '#~' | wc -c | tr -d ' ')
if [ "$count" -gt 0 ]; then pass "при -p 30 в саду есть препятствия ($count)"; else fail "при -p 30 препятствий нет"; fi
file_has "в баннере указаны доля и зерно" "$f1" "Доля препятствий 30%, зерно 7"
run_to_file "$f0" ./garden_sem -W 10 -H 6 -p 0 -r 7 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/ratio0.log"
file_has "при -p 0 препятствий нет" "$f0" "препятствий 0"
count=$(extract_grid "$f0" "начальное состояние сада" 6 | tr -cd '#~' | wc -c | tr -d ' ')
expect_count "при -p 0 на карте нет препятствий" 0 "$count"

printf '\n=== Пруды и камни ===\n'
for program in garden_sem garden_cv; do
    out="$RESULT_DIR/${program}_ponds.out"
    run_to_file "$out" "./$program" -m tests/map_ponds.txt -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/${program}_ponds.log"
    expect_rc_either "$program: карта с прудами" 0 2 "$RUN_RC"
    file_has "$program: пруд пропускается как недоступная клетка" "$out" "[~]"
    grid=$(extract_grid "$out" "начальное состояние сада" 3 | tr '\n' '/')
    if [ "$grid" = "1.~../.#.../...~2/" ]; then
        pass "$program: начальная карта с прудами (камень #, пруды ~, садовники 1 и 2)"
    else
        fail "$program: начальная карта с прудами: '$grid', ожидалось '1.~../.#.../...~2/'"
    fi
    check_log "$program: пруды" "$RESULT_DIR/${program}_ponds.log"
done

printf '\n=== Режимы вывода карты ===\n'
run_capture ./garden_sem -m tests/map_route_independence.txt -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/view0.log"
expect_no_text "-v 0: карта после обработки не выводится" "-- клетка обработана"
expect_no_text "-v 0: карта после перехода не выводится" "-- после перехода"
expect_text "-v 0: итоговая карта выводится" "итоговое состояние сада"
run_capture ./garden_sem -m tests/map_route_independence.txt -t 0,0 -k 0,0 -v 1 -l "$RESULT_DIR/view1.log"
expect_text "-v 1: карта после обработки" "-- клетка обработана"
expect_no_text "-v 1: карта после перехода не выводится" "-- после перехода"
run_capture ./garden_sem -m tests/map_route_independence.txt -t 0,0 -k 0,0 -v 2 -l "$RESULT_DIR/view2b.log"
expect_text "-v 2: карта после обработки" "-- клетка обработана"
expect_text "-v 2: карта после перехода" "-- после перехода"

printf '\n=== Скорость и время обработки каждого садовника ===\n'
run_capture ./garden_sem -m tests/map_route_independence.txt -t 0,5 -k 7,0 -v 0 -l "$RESULT_DIR/speeds.log"
expect_text "садовник 1: переход 0 мс, обработка 7 мс" "переход 0 мс, обработка 7 мс"
expect_text "садовник 2: переход 5 мс, обработка 0 мс" "переход 5 мс, обработка 0 мс"
run_to_file "$RESULT_DIR/speeds_single.out" ./garden_sem -m tests/map_route_independence.txt -t 3 -k 4 -v 0 -l "$RESULT_DIR/speeds_single.log"
count=$(grep -c "переход 3 мс, обработка 4 мс" "$RESULT_DIR/speeds_single.out")
expect_count "одно значение -t/-k применяется к обоим садовникам" 2 "$count"

printf '\n=== Журнал и вывод ===\n'
run_to_file "$RESULT_DIR/nolog.out" ./garden_sem -m tests/map_route_independence.txt -t 0,0 -k 0,0 -v 0 -l /nonexistent_directory/x.log
expect_rc "недоступный журнал не мешает работе" 0 "$RUN_RC"
file_has "предупреждение о журнале" "$RESULT_DIR/nolog.out" "Предупреждение: лог"
file_has "в баннере указано отсутствие журнала" "$RESULT_DIR/nolog.out" "лог: -"
for program in garden_sem garden_cv; do
    ./"$program" -W 4 -H 3 -p 0 -t 0,0 -k 0,0 -v 1 -l "$RESULT_DIR/${program}_same.log" > "$RESULT_DIR/${program}_same.out" 2>/dev/null
    cmp -s "$RESULT_DIR/${program}_same.out" "$RESULT_DIR/${program}_same.log" && pass "$program: журнал совпадает с выводом на экран" || fail "$program: журнал и вывод различаются"
done
rm -f "$RESULT_DIR/pipe_rc.txt"
{ ./garden_sem -m tests/map_route_independence.txt -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/pipe.log"; echo $? > "$RESULT_DIR/pipe_rc.txt"; } | head -n 1 > /dev/null
pipe_rc=$(cat "$RESULT_DIR/pipe_rc.txt" 2>/dev/null)
expect_rc "закрытый канал вывода не убивает программу" 0 "${pipe_rc:-none}"
file_has "после закрытия канала журнал дописан до итога" "$RESULT_DIR/pipe.log" "ИТОГ"

printf '\n=== Большой сад 60x40 ===\n'
for program in garden_sem garden_cv; do
    out="$RESULT_DIR/${program}_big.out"
    run_to_file "$out" "./$program" -W 60 -H 40 -p 0 -t 0,0 -k 0,0 -v 0 -l "$RESULT_DIR/${program}_big.log"
    expect_rc_either "$program: сад 60x40" 0 2 "$RUN_RC"
    file_has "$program: 60x40 — нарушений инвариантов нет" "$out" "нарушений: 0"
    check_log "$program: 60x40" "$RESULT_DIR/${program}_big.log"
done

printf '\n=== Диалог ввода: конец ввода, ошибки, сигналы ===\n'
DLG="-t 0,0 -k 0,0 -v 0 -p 0"
for program in garden_sem garden_cv; do
    p="./$program"
    printf '' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_eof.log" > "$RESULT_DIR/dlg_eof.out" 2>&1
    expect_rc "$program: пустой ввод (EOF)" 0 $?
    file_has "$program: сообщение о конце ввода" "$RESULT_DIR/dlg_eof.out" "Ввод прерван (конец входных данных)"
    file_has "$program: значения командной строки стали умолчаниями диалога" "$RESULT_DIR/dlg_eof.out" "Сад 1 x 2"

    $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_closed.log" <&- > "$RESULT_DIR/dlg_closed.out" 2>&1
    expect_rc "$program: закрытый stdin" 0 $?
    file_has "$program: закрытый stdin — умолчания" "$RESULT_DIR/dlg_closed.out" "Сад 1 x 2"

    $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_null.log" < /dev/null > "$RESULT_DIR/dlg_null.out" 2>&1
    expect_rc "$program: stdin = /dev/null" 0 $?

    printf -- '-\n5\n' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_part.log" > "$RESULT_DIR/dlg_part.out" 2>&1
    expect_rc_either "$program: EOF посреди ввода" 0 2 $?
    file_has "$program: ширина из ввода, высота по умолчанию" "$RESULT_DIR/dlg_part.out" "Сад 1 x 5"

    printf -- '-\n5' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_nonl.log" > "$RESULT_DIR/dlg_nonl.out" 2>&1
    expect_rc_either "$program: последняя строка без перевода строки" 0 2 $?
    file_has "$program: ввод без \\n принят" "$RESULT_DIR/dlg_nonl.out" "Сад 1 x 5"

    printf -- '-\nabc\n99\n3\n' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_bad.log" > "$RESULT_DIR/dlg_bad.out" 2>&1
    expect_rc_either "$program: неверные числа, затем верное" 0 2 $?
    file_has "$program: подсказка о диапазоне" "$RESULT_DIR/dlg_bad.out" "ожидается целое число от 1 до 60"
    file_has "$program: принято значение после повторов" "$RESULT_DIR/dlg_bad.out" "Сад 1 x 3"

    printf -- '-\nx\nx\nx\nx\nx\n' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_five.log" > "$RESULT_DIR/dlg_five.out" 2>&1
    expect_rc "$program: пять неверных вводов подряд" 0 $?
    file_has "$program: сообщение о значении по умолчанию" "$RESULT_DIR/dlg_five.out" "слишком много неверных вводов"
    file_has "$program: использована ширина по умолчанию" "$RESULT_DIR/dlg_five.out" "Сад 1 x 2"

    printf -- '-\r\n4\r\n' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_crlf.log" > "$RESULT_DIR/dlg_crlf.out" 2>&1
    expect_rc_either "$program: перевод строки CRLF" 0 2 $?
    file_has "$program: CRLF принят" "$RESULT_DIR/dlg_crlf.out" "Сад 1 x 4"

    printf -- '  -  \n  3  \n' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_spaces.log" > "$RESULT_DIR/dlg_spaces.out" 2>&1
    expect_rc_either "$program: пробелы вокруг ответов" 0 2 $?
    file_has "$program: пробелы обрезаны" "$RESULT_DIR/dlg_spaces.out" "Сад 1 x 3"

    { printf -- '-\n'; head -c 20000 /dev/zero | tr '\0' 'x'; printf '\n4\n'; } | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_long.log" > "$RESULT_DIR/dlg_long.out" 2>&1
    expect_rc_either "$program: очень длинная строка" 0 2 $?
    file_has "$program: после длинной строки ввод продолжается" "$RESULT_DIR/dlg_long.out" "Сад 1 x 4"

    printf -- '\001\002\377\376\n' | $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_garbage.log" > "$RESULT_DIR/dlg_garbage.out" 2>&1
    expect_rc "$program: мусорные байты вместо имени карты" 1 $?
    file_has "$program: сообщение о карте" "$RESULT_DIR/dlg_garbage.out" "Не могу открыть карту"

    printf -- 'tests/map_route_independence.txt\n' | $p -i $DLG -l "$RESULT_DIR/dlg_map.log" > "$RESULT_DIR/dlg_map.out" 2>&1
    expect_rc "$program: карта из файла через диалог" 0 $?
    file_has "$program: имя карты в баннере" "$RESULT_DIR/dlg_map.out" "карта: tests/map_route_independence.txt"

    printf -- '/nonexistent/map.txt\n' | $p -i $DLG -l "$RESULT_DIR/dlg_nomap.log" > "$RESULT_DIR/dlg_nomap.out" 2>&1
    expect_rc "$program: несуществующая карта через диалог" 1 $?

    printf -- '-\n5\n4\n0\n0\n\n2,2\n\n\n\n3,4\n' | $p -i $DLG -l "$RESULT_DIR/dlg_starts.log" > "$RESULT_DIR/dlg_starts.out" 2>&1
    expect_rc_either "$program: старты через диалог" 0 2 $?
    file_has "$program: старт садовника 1 из диалога" "$RESULT_DIR/dlg_starts.out" "Садовник 1: старт (2,2)"
    file_has "$program: старт садовника 2 из диалога" "$RESULT_DIR/dlg_starts.out" "Садовник 2: старт (3,4)"

    printf -- '-\n5\n4\n0\n0\n\n2,2\n\n\n\n2,2\n' | $p -i $DLG -l "$RESULT_DIR/dlg_same.log" > "$RESULT_DIR/dlg_same.out" 2>&1
    expect_rc "$program: одинаковые старты через диалог" 1 $?
    file_has "$program: сообщение о совпадающих стартах" "$RESULT_DIR/dlg_same.out" "совпадают"

    printf -- '-\n5\n4\n0\n0\n\n9,9\n' | $p -i $DLG -l "$RESULT_DIR/dlg_range.log" > "$RESULT_DIR/dlg_range.out" 2>&1
    expect_rc "$program: старт вне сада через диалог" 1 $?

    printf -- '-\n5\n4\n0\n0\nZZ\nTR:cols\n' | $p -i $DLG -l "$RESULT_DIR/dlg_route.log" > "$RESULT_DIR/dlg_route.out" 2>&1
    expect_rc_either "$program: неверный маршрут, затем верный" 0 2 $?
    file_has "$program: сообщение о маршруте" "$RESULT_DIR/dlg_route.out" "неверная спецификация маршрута"
    file_has "$program: принят маршрут TR:cols" "$RESULT_DIR/dlg_route.out" "правый верхний угол, змейка по столбцам"

    # Сигналы во время диалога: stdin — FIFO без данных
    for sig in INT TERM; do
        make_fifo || continue
        $p -i $DLG -l "$RESULT_DIR/dlg_sig.log" < "$fifo" > "$RESULT_DIR/dlg_sig_$sig.out" 2>&1 &
        pid=$!
        exec 3> "$fifo"
        sleep 0.4
        kill -"$sig" "$pid" 2>/dev/null
        wait_timeout "$pid" 10
        exec 3>&-
        expect_rc "$program: SIG$sig во время диалога" 3 "$WAIT_RC"
        file_has "$program: SIG$sig — сообщение об отмене ввода" "$RESULT_DIR/dlg_sig_$sig.out" "Ввод прерван сигналом"
        file_lacks "$program: SIG$sig — модель не запускалась" "$RESULT_DIR/dlg_sig_$sig.out" "приступил к работе"
    done

    # SIGUSR1 во время диалога не мешает вводу и не печатает карту модели
    if make_fifo; then
    $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_usr1.log" < "$fifo" > "$RESULT_DIR/dlg_usr1.out" 2>&1 &
    pid=$!
    exec 3> "$fifo"
    sleep 0.3
    kill -USR1 "$pid" 2>/dev/null
    sleep 0.2
    kill -USR1 "$pid" 2>/dev/null
    printf -- '-\n3\n' >&3
    exec 3>&-
    wait_timeout "$pid" 15
    expect_rc_either "$program: SIGUSR1 во время диалога" 0 2 "$WAIT_RC"
    file_has "$program: ввод после SIGUSR1 принят" "$RESULT_DIR/dlg_usr1.out" "Сад 1 x 3"
    file_lacks "$program: карта по SIGUSR1 из диалога не выводится" "$RESULT_DIR/dlg_usr1.out" "состояние по запросу"
    fi

    # Ввод закрывается во время ожидания
    if make_fifo; then
    $p -i -W 2 -H 1 $DLG -l "$RESULT_DIR/dlg_late_eof.log" < "$fifo" > "$RESULT_DIR/dlg_late_eof.out" 2>&1 &
    pid=$!
    exec 3> "$fifo"
    printf -- '-\n' >&3
    sleep 0.4
    exec 3>&-
    wait_timeout "$pid" 15
    expect_rc "$program: закрытие ввода во время диалога" 0 "$WAIT_RC"
    file_has "$program: сообщение о конце ввода" "$RESULT_DIR/dlg_late_eof.out" "Ввод прерван (конец входных данных)"
    fi
done

printf '\n=== Сигналы во время моделирования ===\n'
for program in garden_sem garden_cv; do
    # SIGTERM
    out="$RESULT_DIR/${program}_term.out"
    "./$program" -W 8 -H 6 -p 0 -t 100,100 -k 1000,1000 -v 0 -l "$RESULT_DIR/${program}_term.log" > "$out" 2>&1 &
    pid=$!
    sleep 0.3
    kill -TERM "$pid" 2>/dev/null
    wait_timeout "$pid" 10
    expect_rc "$program: SIGTERM" 3 "$WAIT_RC"
    file_has "$program: SIGTERM — причина в итоге" "$out" "прервано сигналом 15"
    count=$(grep -c "завершает работу" "$out")
    expect_count "$program: SIGTERM — оба садовника освободили клетки" 2 "$count"
    file_has "$program: SIGTERM — итоговая статистика" "$out" "Проверки инвариантов:"
    check_log "$program: SIGTERM" "$RESULT_DIR/${program}_term.log"

    # SIGINT во время обработки клетки: обработка прерывается, клетка не засчитывается
    out="$RESULT_DIR/${program}_int_work.out"
    "./$program" -W 4 -H 2 -p 0 -t 10,10 -k 2000,2000 -v 0 -l "$RESULT_DIR/${program}_int_work.log" > "$out" 2>&1 &
    pid=$!
    sleep 0.5
    kill -INT "$pid" 2>/dev/null
    wait_timeout "$pid" 10
    expect_rc "$program: SIGINT во время обработки" 3 "$WAIT_RC"
    file_has "$program: обработка прервана" "$out" "прервана"
    file_has "$program: прерванные клетки не засчитаны" "$out" "Обработано клеток: 0 из 8"
    check_log "$program: прерванная обработка" "$RESULT_DIR/${program}_int_work.log"

    # SIGUSR1: карта без остановки
    out="$RESULT_DIR/${program}_usr1.out"
    "./$program" -W 6 -H 3 -p 0 -t 50,50 -k 100,100 -v 0 -l "$RESULT_DIR/${program}_usr1.log" > "$out" 2>&1 &
    pid=$!
    sleep 0.3
    kill -USR1 "$pid" 2>/dev/null
    sleep 0.3
    kill -USR1 "$pid" 2>/dev/null
    wait_timeout "$pid" 40
    expect_rc_either "$program: SIGUSR1 не останавливает моделирование" 0 2 "$WAIT_RC"
    file_has "$program: карта по запросу выведена" "$out" "состояние по запросу (SIGUSR1)"
    check_log "$program: SIGUSR1" "$RESULT_DIR/${program}_usr1.log"
done

printf '\n=== Файл конфигурации (-f) ===\n'
cfgd="$RESULT_DIR/configs"
mkdir -p "$cfgd"
printf '3 4 0 0 0 0 0 0 0\n' > "$cfgd/basic.txt"
printf '# сад 4x5\n4 5 0\n0 0 0 0\n1 0   # d1=1, d2=0\n2 2 3 4 columns\n1 3 3 3\n' > "$cfgd/full.txt"
printf '3\n4\n0\n0 0 0 0\n0 0\n' > "$cfgd/multiline.txt"
printf '3 4 0 0 0 0 0 0 0\r\n' > "$cfgd/crlf.txt"
printf '3 4 0 0 0 0 0 true false\n' > "$cfgd/bool.txt"
printf '4 5 0.2 0 0 0 0 0 0\n' > "$cfgd/ratio.txt"
: > "$cfgd/empty.txt"
printf '3 4 0 0 0\n' > "$cfgd/few.txt"
printf '3 x 0 0 0 0 0 0 0\n' > "$cfgd/nonnum.txt"
printf '0 4 0 0 0 0 0 0 0\n' > "$cfgd/h0.txt"
printf '41 4 0 0 0 0 0 0 0\n' > "$cfgd/h41.txt"
printf '3 4 0.95 0 0 0 0 0 0\n' > "$cfgd/ratio_high.txt"
printf '3 4 -0.1 0 0 0 0 0 0\n' > "$cfgd/ratio_neg.txt"
printf '3 4 0 100001 0 0 0 0 0\n' > "$cfgd/time_high.txt"
printf '3 4 0 0 0 0 0 2 0\n' > "$cfgd/bad_d1.txt"
printf '3 4 0 0 0 0 0 0 0 1 1 2\n' > "$cfgd/partial_starts.txt"
printf '3 4 0 0 0 0 0 0 0 diagonal\n' > "$cfgd/garbage_tail.txt"
printf '3 4 0 0 0 0 0 0 0 1 1 3 4 2\n' > "$cfgd/odd_obstacles.txt"
printf '3 4 0 0 0 0 0 0 0 1 1 3 4 9 9\n' > "$cfgd/obstacle_outside.txt"
printf '3 4 0 0 0 0 0 0 0 1 1 3 4 1 1\n' > "$cfgd/obstacle_on_start.txt"
printf '3 4 0 0 0 0 0 0 0 5 1 3 4\n' > "$cfgd/start_outside.txt"
printf '3 4 0 0 0 0 0 0 0 2 2 2 2\n' > "$cfgd/same_starts.txt"

for program in garden_sem garden_cv; do
    f="$RESULT_DIR/${program}_cfg_basic.out"
    run_to_file "$f" "./$program" -f "$cfgd/basic.txt" -v 0 -l "$RESULT_DIR/${program}_cfg_basic.log"
    expect_rc_either "$program: минимальный файл конфигурации" 0 2 "$RUN_RC"
    file_has "$program: размеры сада из файла" "$f" "Сад 3 x 4"
    file_has "$program: время из файла" "$f" "переход 0 мс, обработка 0 мс"
    file_has "$program: обход по умолчанию запрещён" "$f" "садовник 1 — запрещён"

    f="$RESULT_DIR/${program}_cfg_full.out"
    run_to_file "$f" "./$program" -f "$cfgd/full.txt" -v 0 -l "$RESULT_DIR/${program}_cfg_full.log"
    expect_rc_either "$program: полный файл конфигурации" 0 2 "$RUN_RC"
    file_has "$program: полный файл — размеры" "$f" "Сад 4 x 5"
    file_has "$program: полный файл — старт садовника 1" "$f" "Садовник 1: старт (2,2)"
    file_has "$program: полный файл — старт садовника 2" "$f" "Садовник 2: старт (3,4)"
    file_has "$program: полный файл — маршрут по столбцам" "$f" "змейка по столбцам"
    file_has "$program: полный файл — два препятствия" "$f" "препятствий 2"
    file_has "$program: полный файл — обход садовника 1 разрешён" "$f" "садовник 1 — разрешён"
    file_has "$program: полный файл — обход садовника 2 запрещён" "$f" "садовник 2 — запрещён"
    file_has "$program: полный файл — препятствие (1,3) пропускается" "$f" "пропускает недоступную клетку (1,3) [#]"
    check_log "$program: файл конфигурации" "$RESULT_DIR/${program}_cfg_full.log"

    f="$RESULT_DIR/${program}_cfg_ratio.out"
    run_to_file "$f" "./$program" -f "$cfgd/ratio.txt" -v 0 -r 5 -l "$RESULT_DIR/${program}_cfg_ratio.log"
    file_has "$program: доля препятствий из файла (0.2 = 20%)" "$f" "Доля препятствий 20%"

    f="$RESULT_DIR/${program}_cfg_override.out"
    run_to_file "$f" "./$program" -f "$cfgd/basic.txt" -W 6 -p 20 -o -v 0 -l "$RESULT_DIR/${program}_cfg_override.log"
    file_has "$program: -W перекрывает файл" "$f" "Сад 3 x 6"
    file_has "$program: -p перекрывает файл" "$f" "Доля препятствий 20%"
    file_has "$program: -o перекрывает файл (садовник 2)" "$f" "садовник 2 — разрешён"

    for name in multiline crlf bool; do
        f="$RESULT_DIR/${program}_cfg_${name}.out"
        run_to_file "$f" "./$program" -f "$cfgd/$name.txt" -v 0 -l "$RESULT_DIR/${program}_cfg_${name}.log"
        expect_rc_either "$program: файл конфигурации '$name'" 0 2 "$RUN_RC"
        file_has "$program: файл '$name' — размеры" "$f" "Сад 3 x 4"
    done
    file_has "$program: true/false в файле" "$RESULT_DIR/${program}_cfg_bool.out" "садовник 2 — запрещён"

    printf '' | "./$program" -i -f "$cfgd/basic.txt" -v 0 -l "$RESULT_DIR/${program}_cfg_dialog.log" > "$RESULT_DIR/${program}_cfg_dialog.out" 2>&1
    expect_rc_either "$program: диалог берёт умолчания из файла" 0 2 $?
    file_has "$program: умолчания диалога из файла" "$RESULT_DIR/${program}_cfg_dialog.out" "Сад 3 x 4"

    for name in empty few nonnum h0 h41 ratio_high ratio_neg time_high bad_d1 partial_starts garbage_tail odd_obstacles obstacle_outside obstacle_on_start start_outside same_starts; do
        expect_exit "$program: неверный файл конфигурации '$name'" 1 "./$program" -f "$cfgd/$name.txt" -v 0 -l "$RESULT_DIR/${program}_cfg_bad.log"
    done
    expect_exit "$program: несуществующий файл конфигурации" 1 "./$program" -f /nonexistent/config.txt
    expect_text "$program: сообщение о файле конфигурации" "файл конфигурации"
    expect_exit "$program: -f без аргумента" 1 "./$program" -f
    expect_exit "$program: каталог вместо файла конфигурации" 1 "./$program" -f "$cfgd"
done

printf '\n=== Проверка журналов ===\n'
for log in "$RESULT_DIR/open_1x2_sem.log" "$RESULT_DIR/open_1x2_cv.log" \
           "$RESULT_DIR/map_islands.log" "$RESULT_DIR/center_island.log"; do
    if [ -s "$log" ]; then
        pass "создан журнал $log"
    else
        fail "журнал пуст или отсутствует: $log"
    fi
done

printf '\n================ ИТОГ ТЕСТИРОВАНИЯ ================\n'
printf 'Успешно: %d\nОшибок:   %d\nПропущено: %d\n' "$passed" "$failed" "$skipped"
[ -n "$FIFO_DIR" ] && rm -rf "$FIFO_DIR"

if [ "$failed" -ne 0 ]; then
    printf 'Список неудачных проверок: %s/failures.txt; подробности — в файлах %s/\n' "$RESULT_DIR" "$RESULT_DIR"
    exit 1
fi
# Всё прошло: служебные файлы тестов больше не нужны (оставить: KEEP_RESULTS=1)
if [ -z "${KEEP_RESULTS:-}" ]; then
    find "$RESULT_DIR" -mindepth 1 -maxdepth 1 ! -name examples -exec rm -rf {} + 2>/dev/null
fi
exit 0

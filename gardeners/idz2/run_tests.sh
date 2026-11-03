#!/bin/sh
# Набор автоматических интеграционных тестов для garden_sem и garden_cv.
# Запускать из корня проекта командой: make test
set -u

RESULT_DIR="test-results"
mkdir -p "$RESULT_DIR"
passed=0
failed=0

pass() {
    printf 'PASS: %s\n' "$1"
    passed=$((passed + 1))
}

fail() {
    printf 'FAIL: %s\n' "$1"
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
    if printf '%s\n' "$TEST_OUTPUT" | grep -Fq "$text"; then
        pass "$name"
    else
        printf '%s\n' "$TEST_OUTPUT" > "$RESULT_DIR/failed_${failed}.txt"
        fail "$name: не найден текст '$text'"
    fi
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


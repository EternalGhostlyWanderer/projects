CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
LDLIBS ?= -pthread

SOURCES = main.c cmd_parser.c config_reader.c garden_map.c gardener.c simulation.c writer.c
HEADERS = $(wildcard *.h)

.PHONY: all clean test asan tsan
all: garden_sem garden_cv

garden_sem: $(SOURCES) $(HEADERS)
	$(CC) $(CFLAGS) $(SOURCES) -o $@ $(LDLIBS)

garden_cv: $(SOURCES) $(HEADERS)
	$(CC) $(CFLAGS) -DUSE_CV $(SOURCES) -o $@ $(LDLIBS)

test: all
	sh tests/run_tests.sh

# Сборка с санитайзерами; затем make test. Для обычной сборки: make clean && make
# asan — ошибки работы с памятью и неопределённое поведение; tsan — гонки данных между потоками
asan:
	$(MAKE) clean
	$(MAKE) CFLAGS="-std=c11 -O1 -g -Wall -Wextra -Wpedantic -fsanitize=address,undefined -fno-omit-frame-pointer" all

tsan:
	$(MAKE) clean
	$(MAKE) CFLAGS="-std=c11 -O1 -g -Wall -Wextra -Wpedantic -fsanitize=thread" all

clean:
	rm -f garden_sem garden_cv garden.log garden_test_sem.log garden_test_cv.log
	rm -rf test-results

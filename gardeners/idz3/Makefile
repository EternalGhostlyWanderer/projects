CC ?= cc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
LDLIBS ?= -pthread -lrt

# Общие модули (структура прошлого ДЗ + shared.c и sync.c)
COMMON = cmd_parser.c config_reader.c garden_map.c gardener.c simulation.c writer.c shared.c sync.c
HEADERS = $(wildcard *.h)

.PHONY: all clean test asan
# garden_named   — fork + shm + именованные семафоры          (4–5 баллов)
# garden_unnamed — fork + shm + неименованные семафоры в shm  (6 баллов)
# garden_init + gardener1 + gardener2 — независимые процессы  (7–8 баллов)
# garden_server + gardener_mq1 + gardener_mq2 — очередь сообщений + семафоры (выше 8)
all: garden_named garden_unnamed garden_init gardener1 gardener2 garden_server gardener_mq1 gardener_mq2

garden_named: main.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) main.c $(COMMON) -o $@ $(LDLIBS)

garden_unnamed: main.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) -DSEM_UNNAMED main.c $(COMMON) -o $@ $(LDLIBS)

garden_init: main.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) -DINDEPENDENT main.c $(COMMON) -o $@ $(LDLIBS)

gardener1: gardener_main.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) -DINDEPENDENT -DGARDENER_ID=0 gardener_main.c $(COMMON) -o $@ $(LDLIBS)

gardener2: gardener_main.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) -DINDEPENDENT -DGARDENER_ID=1 gardener_main.c $(COMMON) -o $@ $(LDLIBS)

garden_server: main.c simulation_mq.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) -DIPC_MQ main.c simulation_mq.c $(COMMON) -o $@ $(LDLIBS)

gardener_mq1: gardener_mq.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) -DIPC_MQ -DGARDENER_ID=0 gardener_mq.c $(COMMON) -o $@ $(LDLIBS)

gardener_mq2: gardener_mq.c $(COMMON) $(HEADERS)
	$(CC) $(CFLAGS) -DIPC_MQ -DGARDENER_ID=1 gardener_mq.c $(COMMON) -o $@ $(LDLIBS)

test: all
	sh tests/run_tests.sh
	sh tests/run_tests_ipc.sh

# Сборка с санитайзерами (память и неопределённое поведение)
asan:
	$(MAKE) clean
	$(MAKE) CFLAGS="-std=c11 -O1 -g -Wall -Wextra -Wpedantic -fsanitize=address,undefined -fno-omit-frame-pointer" all

clean:
	rm -f garden_named garden_unnamed garden_init gardener1 gardener2 garden_server gardener_mq1 gardener_mq2 garden.log garden_test_*.log
	rm -rf test-results

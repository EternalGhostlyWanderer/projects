/* Независимый процесс-садовник (gardener1 / gardener2).
 * Запускается отдельно от garden_init, присоединяется к shm POSIX и
 * именованным семафорам с тем же базовым именем (-n). Номер садовника
 * задаётся при сборке: -DGARDENER_ID=0 или 1. */
#define _GNU_SOURCE
#include "simulation_internal.h"
#include "simulation.h"
#include "shared.h"
#include "gardener.h"

#ifndef GARDENER_ID
#error "Укажите -DGARDENER_ID=0 или 1"
#endif

static void usage(const char *prog)
{
    char b[512];
    int n = snprintf(b, sizeof b,
        "Садовник %d — независимый процесс (%s).\n"
        "Использование: %s [-n ИМЯ]\n"
        "  -n ИМЯ  базовое имя IPC, как у garden_init (по умолчанию /garden)\n"
        "Запускается после (или во время) garden_init из того же каталога.\n",
        GARDENER_ID + 1, IMPL_NAME, prog);
    write_all(1, b, (size_t)n);
}

int main(int argc, char **argv)
{
    int opt;
    opterr = 0;
    snprintf(cfg.base, sizeof cfg.base, "/garden");
    install_signal_handlers();
    while ((opt = getopt(argc, argv, "n:h")) != -1) {
        if (opt == 'n') snprintf(cfg.base, sizeof cfg.base, "%s", optarg);
        else if (opt == 'h') { usage(argv[0]); return 0; }
        else { err_msg("Неверный параметр (справка: -h)"); return 1; }
    }
    const char *base = ipc_base();

    if (!shared_attach(base)) return sig_stop ? 3 : 1;
    /* Ждём, пока garden_init построит сад и создаст семафоры. */
    for (int i = 0; i < 300 && !atomic_load(&S->world_ready) && !sig_stop; i++) {
        struct timespec ts = {0, 100 * 1000000L};
        nanosleep(&ts, NULL);
    }
    if (!atomic_load(&S->world_ready)) {
        err_msg("garden_init не подготовил модель (%s)", base);
        shared_detach();
        return sig_stop ? 3 : 1;
    }
    if (!prims_attach(base)) {
        shared_detach();
        return 1;
    }

    log_fd = open(cfg.log_path, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (log_fd < 0)
        err_msg("Предупреждение: лог '%s' не открыт: %s", cfg.log_path, strerror(errno));

    lock();
    gd[GARDENER_ID].pid = getpid();
    unlock();
    ready_signal();          /* сообщаем garden_init о готовности */
    gardener_run(GARDENER_ID);

    prims_close();
    shared_detach();
    if (log_fd >= 0) close(log_fd);
    return 0;
}

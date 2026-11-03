/* ipcprobe ИМЯ — проверяет, что объекты IPC с базовым именем ИМЯ удалены:
 * разделяемая память, именованные семафоры и очереди сообщений.
 * Код выхода 0 — ничего не осталось, 1 — остатки найдены (имена выводятся). */
#include <fcntl.h>
#include <mqueue.h>
#include <semaphore.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    if (argc < 2) return 2;
    int left = 0;
    char nm[160];
    int fd = shm_open(argv[1], O_RDONLY, 0);
    if (fd >= 0) { printf("осталась shm %s\n", argv[1]); close(fd); left = 1; }
    const char *sfx[] = {"_m", "_s", "_r", "_d", "_c0", "_c1", "_c5"};
    for (unsigned i = 0; i < sizeof sfx / sizeof *sfx; i++) {
        snprintf(nm, sizeof nm, "%s%s", argv[1], sfx[i]);
        sem_t *s = sem_open(nm, 0);
        if (s != SEM_FAILED) { printf("остался семафор %s\n", nm); sem_close(s); left = 1; }
    }
    const char *q[] = {"_q", "_a0", "_a1"};
    for (unsigned i = 0; i < sizeof q / sizeof *q; i++) {
        snprintf(nm, sizeof nm, "%s%s", argv[1], q[i]);
        mqd_t m = mq_open(nm, O_RDONLY);
        if (m != (mqd_t)-1) { printf("осталась очередь %s\n", nm); mq_close(m); left = 1; }
    }
    return left;
}

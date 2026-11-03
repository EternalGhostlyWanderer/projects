#define _GNU_SOURCE
#include "simulation_internal.h"
#include "shared.h"

#undef sig_stop /* здесь нужен доступ к полю sig_stop разных экземпляров Shared */

/* Локальная копия состояния: используется, пока shm ещё не создана
 * (разбор параметров и диалог), затем содержимое переносится в shm. */
static Shared local_store;
Shared *S = &local_store;

static char shm_name[96];
static pid_t shm_creator = 0;   /* процесс, создавший shm (только он её удаляет) */
static char base_buf[96];

/* Базовое имя объектов IPC: из параметра -n либо "/garden_<pid>". */
const char *ipc_base(void)
{
    if (base_buf[0]) return base_buf;
    if (cfg.base[0]) {
        snprintf(base_buf, sizeof base_buf, "%s%s", cfg.base[0] == '/' ? "" : "/", cfg.base);
    } else {
        snprintf(base_buf, sizeof base_buf, "/garden_%d", (int)getpid());
    }
    return base_buf;
}

/* Создаёт раздел shm, переносит в него локальное состояние и переключает S. */
int shared_create(const char *base)
{
    snprintf(shm_name, sizeof shm_name, "%s", base);
    shm_unlink(shm_name); /* устаревший объект после аварийного завершения */
    int fd = shm_open(shm_name, O_CREAT | O_EXCL | O_RDWR, 0600);
    if (fd < 0) {
        err_msg("shm_open('%s'): %s", shm_name, strerror(errno));
        return 0;
    }
    if (ftruncate(fd, (off_t)sizeof(Shared)) < 0) {
        err_msg("ftruncate: %s", strerror(errno));
        close(fd);
        shm_unlink(shm_name);
        return 0;
    }
    void *p = mmap(NULL, sizeof(Shared), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd); /* отображение остаётся и после закрытия дескриптора */
    if (p == MAP_FAILED) {
        err_msg("mmap: %s", strerror(errno));
        shm_unlink(shm_name);
        return 0;
    }
    memcpy(p, S, sizeof(Shared));
    Shared *old = S;
    S = p;
    int pending = atomic_load(&old->sig_stop);
    if (pending && !atomic_load(&S->sig_stop)) atomic_store(&S->sig_stop, pending); /* сигнал, пришедший при копировании */
    shm_creator = getpid();
    return 1;
}

/* Присоединяется к уже созданной shm (до 30 с ждём её появления). */
int shared_attach(const char *base)
{
    snprintf(shm_name, sizeof shm_name, "%s", base);
    int fd = -1;
    for (int i = 0; i < 300 && !atomic_load(&S->sig_stop); i++) {
        fd = shm_open(shm_name, O_RDWR, 0600);
        if (fd >= 0) {
            struct stat st;
            if (fstat(fd, &st) == 0 && (size_t)st.st_size >= sizeof(Shared)) break;
            close(fd); /* shm создана, но ещё не имеет нужного размера */
            fd = -1;
        }
        struct timespec ts = {0, 100 * 1000000L};
        nanosleep(&ts, NULL);
    }
    if (fd < 0) {
        err_msg("Не найдена разделяемая память '%s': запустите garden_init с тем же -n", shm_name);
        return 0;
    }
    void *p = mmap(NULL, sizeof(Shared), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (p == MAP_FAILED) {
        err_msg("mmap: %s", strerror(errno));
        return 0;
    }
    S = p;
    return 1;
}

void shared_detach(void)
{
    if (S != &local_store) {
        munmap(S, sizeof(Shared));
        S = &local_store;
    }
}

/* Удаление shm: только создатель; безопасно вызывать повторно. */
void shared_unlink(void)
{
    if (shm_creator == getpid() && shm_name[0]) {
        shm_unlink(shm_name);
        shm_creator = 0;
    }
}

int shared_is_creator(void) { return shm_creator == getpid(); }

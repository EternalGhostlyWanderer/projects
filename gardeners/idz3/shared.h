#ifndef SHARED_H
#define SHARED_H

// Базовое имя объектов IPC ("/garden_<pid>" или значение -n)
const char *ipc_base(void);
// Текущий процесс создал shm и должен её удалить
int shared_is_creator(void);

#endif

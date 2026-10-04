/* Lanceur de Rangeur.app : c'est cette petite app qui reçoit l'accès complet au disque
   (nécessaire pour lire Téléchargements et iCloud en arrière-plan). Le script qu'elle lance
   en hérite ; rien d'autre sur le Mac n'obtient cet accès.
   Compilation (faite par installer.sh) : clang -O2 -DRANGEUR_PY='"/chemin/rangeur.py"' ... */
#include <spawn.h>
#include <sys/wait.h>
#ifndef RANGEUR_PY
#error "compiler avec -DRANGEUR_PY=\"/chemin/vers/rangeur.py\""
#endif
extern char **environ;
int main(void) {
    char *argv[] = {"/usr/bin/python3", RANGEUR_PY, NULL};
    pid_t pid; int st = 0;
    if (posix_spawn(&pid, "/usr/bin/python3", NULL, NULL, argv, environ) != 0) return 1;
    waitpid(pid, &st, 0);
    return WIFEXITED(st) ? WEXITSTATUS(st) : 1;
}

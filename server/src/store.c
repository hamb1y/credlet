#define _POSIX_C_SOURCE 200809L
#include "credlet.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <direct.h>
#include <io.h>
#include <windows.h>
#include <sddl.h>
#define close _close
#define open _open
#define mkdir(path, mode) _mkdir(path)
#else
#include <unistd.h>
#endif

static int private_path(const char *path, bool directory) {
#ifdef _WIN32
    PSECURITY_DESCRIPTOR descriptor = NULL;
    const char *acl = directory ? "D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)" : "D:P(A;;FA;;;OW)(A;;FA;;;SY)";
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorA(acl, SDDL_REVISION_1, &descriptor, NULL)) return -1;
    BOOL ok = SetFileSecurityA(path, DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION, descriptor);
    LocalFree(descriptor);
    return ok ? 0 : -1;
#else
    return chmod(path, directory ? 0700 : 0600);
#endif
}

int exec_sql(sqlite3 *db, const char *sql) {
    return sqlite3_exec(db, sql, NULL, NULL, NULL) == SQLITE_OK ? 0 : -1;
}

char *meta_get(sqlite3 *db, const char *key) {
    sqlite3_stmt *stmt = NULL;
    char *result = NULL;
    if (sqlite3_prepare_v2(db, "SELECT value FROM meta WHERE key=?", -1, &stmt, NULL) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, key, -1, SQLITE_TRANSIENT);
        if (sqlite3_step(stmt) == SQLITE_ROW) {
            const char *value = (const char *)sqlite3_column_text(stmt, 0);
            if (value) result = strdup(value);
        }
    }
    sqlite3_finalize(stmt);
    return result;
}

int meta_set(sqlite3 *db, const char *key, const char *value) {
    sqlite3_stmt *stmt = NULL;
    int result = -1;
    if (sqlite3_prepare_v2(db, "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", -1, &stmt, NULL) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, key, -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 2, value, -1, SQLITE_TRANSIENT);
        if (sqlite3_step(stmt) == SQLITE_DONE) result = 0;
    }
    sqlite3_finalize(stmt);
    return result;
}

int store_open(struct server *server, const char *state, bool create) {
    char path[4096];
    struct stat info;
    if (create && mkdir(state, 0700) && errno != EEXIST) return -1;
    if (stat(state, &info) || !S_ISDIR(info.st_mode)) return -1;
#ifndef _WIN32
    struct stat link_info;
    if (lstat(state, &link_info) || S_ISLNK(link_info.st_mode) || info.st_uid != geteuid()) return -1;
#endif
    if (private_path(state, true)) return -1;
    if (snprintf(path, sizeof(path), "%s/vault.sqlite3", state) >= (int)sizeof(path)) return -1;
    if (create) {
        int fd = open(path, O_CREAT | O_EXCL | O_WRONLY, 0600);
        if (fd < 0) return -1;
        close(fd);
    }
    if (private_path(path, false)) return -1;
    if (sqlite3_open_v2(path, &server->db, SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX, NULL) != SQLITE_OK) return -1;
    sqlite3_busy_timeout(server->db, 5000);
    if (exec_sql(server->db, "PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA secure_delete=ON;")) return -1;
    if (create) return 0;
    char *version = meta_get(server->db, "schema");
    char *pk = meta_get(server->db, "public_key"), *sk = meta_get(server->db, "secret_key");
    int ok = version && !strcmp(version, "1") && !decode64(pk, server->pk, sizeof(server->pk)) && !decode64(sk, server->sk, sizeof(server->sk));
    if (sk) sodium_memzero(sk, strlen(sk));
    free(version); free(pk); free(sk);
    return ok ? 0 : -1;
}

void store_close(struct server *server) {
    if (server->db) sqlite3_close(server->db);
    server->db = NULL;
    sodium_memzero(server->sk, sizeof(server->sk));
}

int store_init(struct server *server, const char *owner) {
    if (exec_sql(server->db,
        "BEGIN IMMEDIATE;"
        "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "CREATE TABLE owner(id INTEGER PRIMARY KEY CHECK(id=1),email TEXT NOT NULL,verifier TEXT NOT NULL,wrapped TEXT NOT NULL);"
        "CREATE TABLE items(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,deleted INTEGER NOT NULL,payload TEXT NOT NULL);"
        "CREATE TABLE sessions(hash BLOB PRIMARY KEY,expires INTEGER NOT NULL);"
        "CREATE TABLE replays(id TEXT PRIMARY KEY,expires INTEGER NOT NULL);")) return -1;
    unsigned char token[32], digest[32], salt[16];
    randombytes_buf(token, sizeof(token)); randombytes_buf(salt, sizeof(salt));
    crypto_generichash(digest, sizeof(digest), token, sizeof(token), NULL, 0);
    if (crypto_box_keypair(server->pk, server->sk)) return -1;
    char *pk = encode64(server->pk, sizeof(server->pk)), *sk = encode64(server->sk, sizeof(server->sk));
    char *salt64 = encode64(salt, sizeof(salt)), *hash = encode64(digest, sizeof(digest)), *token64 = encode64(token, sizeof(token));
    int result = !pk || !sk || !salt64 || !hash || !token64 ||
        meta_set(server->db,"schema","1") || meta_set(server->db,"public_key",pk) ||
        meta_set(server->db,"secret_key",sk) || meta_set(server->db,"salt",salt64) ||
        meta_set(server->db,"enrollment",hash) || meta_set(server->db,"owner",owner) ||
        meta_set(server->db,"revision","0") || exec_sql(server->db,"COMMIT");
    if (!result) printf("{\"version\":\"%s\",\"serverKey\":\"%s\",\"enrollmentToken\":\"%s\"}\n", CREDLET_VERSION, pk, token64);
    if (sk) sodium_memzero(sk, strlen(sk));
    if (token64) sodium_memzero(token64, strlen(token64));
    sodium_memzero(token, sizeof(token));
    free(pk); free(sk); free(salt64); free(hash); free(token64);
    return result ? -1 : 0;
}

int print_pairing(struct server *server) {
    char *pk = encode64(server->pk, sizeof(server->pk));
    if (!pk) return -1;
    printf("{\"version\":\"%s\",\"serverKey\":\"%s\"}\n", CREDLET_VERSION, pk);
    free(pk);
    return 0;
}

int store_backup(struct server *server, const char *destination) {
    int fd = open(destination, O_CREAT | O_EXCL | O_WRONLY, 0600);
    if (fd < 0) return -1;
    close(fd);
    if (private_path(destination, false)) return -1;
    sqlite3 *target = NULL;
    if (sqlite3_open_v2(destination, &target, SQLITE_OPEN_READWRITE, NULL) != SQLITE_OK) {
        sqlite3_close(target); return -1;
    }
    sqlite3_backup *backup = sqlite3_backup_init(target, "main", server->db, "main");
    int result = backup ? sqlite3_backup_step(backup, -1) : SQLITE_ERROR;
    if (backup) sqlite3_backup_finish(backup);
    sqlite3_close(target);
    return result == SQLITE_DONE ? 0 : -1;
}

int store_restore(struct server *server, const char *source) {
    sqlite3 *backup_db=NULL;
    if(sqlite3_open_v2(source,&backup_db,SQLITE_OPEN_READONLY,NULL)!=SQLITE_OK) {
        sqlite3_close(backup_db); return -1;
    }
    sqlite3_stmt *stmt=NULL;
    bool valid=false;
    if(sqlite3_prepare_v2(backup_db,"PRAGMA integrity_check",-1,&stmt,NULL)==SQLITE_OK && sqlite3_step(stmt)==SQLITE_ROW)
        valid=!strcmp((const char *)sqlite3_column_text(stmt,0),"ok");
    sqlite3_finalize(stmt);
    char *version=meta_get(backup_db,"schema"), *pk=meta_get(backup_db,"public_key"), *sk=meta_get(backup_db,"secret_key");
    unsigned char public_key[32], secret_key[32], derived[32];
    valid=valid && version && !strcmp(version,"1") && !decode64(pk,public_key,sizeof(public_key)) && !decode64(sk,secret_key,sizeof(secret_key));
    if(valid) { crypto_scalarmult_base(derived,secret_key); valid=!sodium_memcmp(derived,public_key,sizeof(derived)); }
    sodium_memzero(secret_key,sizeof(secret_key));
    if(sk) sodium_memzero(sk,strlen(sk));
    free(version); free(pk); free(sk);
    int result=SQLITE_ERROR;
    if(valid) {
        sqlite3_backup *backup=sqlite3_backup_init(server->db,"main",backup_db,"main");
        if(backup) { result=sqlite3_backup_step(backup,-1); sqlite3_backup_finish(backup); }
    }
    sqlite3_close(backup_db);
    if(result!=SQLITE_DONE) return -1;
    // A restored backup keeps the server identity, but never revives sessions.
    return exec_sql(server->db,"DELETE FROM sessions;");
}

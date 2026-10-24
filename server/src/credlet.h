#ifndef CREDLET_H
#define CREDLET_H
#include <stdbool.h>
#include <stdint.h>
#include <json-c/json.h>
#include <sodium.h>
#include <sqlite3.h>

#define CREDLET_VERSION "0.3.0-dev"
#define MAX_MESSAGE (256 * 1024)
#define MAX_ITEM (64 * 1024)
#define SESSION_SECONDS 300

struct server {
    sqlite3 *db;
    unsigned char pk[crypto_box_PUBLICKEYBYTES], sk[crypto_box_SECRETKEYBYTES];
    int login_attempts;
    int64_t login_window;
};

const char *jstr(json_object *obj, const char *key, size_t maximum);
int64_t jint(json_object *obj, const char *key, int64_t fallback);
json_object *parse_json(const char *data, size_t len);
char *encode64(const unsigned char *data, size_t len);
int decode64(const char *s, unsigned char *out, size_t length);
json_object *failure(int status, const char *message);
json_object *success(json_object *data);
int exec_sql(sqlite3 *db, const char *sql);
char *meta_get(sqlite3 *db, const char *key);
int meta_set(sqlite3 *db, const char *key, const char *value);
int store_open(struct server *server, const char *state, bool create);
void store_close(struct server *server);
int store_init(struct server *server, const char *owner);
int store_backup(struct server *server, const char *destination);
int store_restore(struct server *server, const char *source);
int print_pairing(struct server *server);
json_object *dispatch(struct server *server, json_object *request);
json_object *exchange(struct server *server, json_object *envelope);
int serve(struct server *server, const char *address, unsigned short port);
#endif

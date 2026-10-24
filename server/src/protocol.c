#define _POSIX_C_SOURCE 200809L
#include "credlet.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

const char *jstr(json_object *obj, const char *key, size_t maximum) {
    json_object *value = NULL;
    if (!obj || !json_object_object_get_ex(obj,key,&value) || !json_object_is_type(value,json_type_string)) return NULL;
    const char *s = json_object_get_string(value);
    size_t n = (size_t)json_object_get_string_len(value);
    return n && n <= maximum && strlen(s) == n ? s : NULL;
}

int64_t jint(json_object *obj, const char *key, int64_t fallback) {
    json_object *value = NULL;
    return obj && json_object_object_get_ex(obj,key,&value) && json_object_is_type(value,json_type_int) ? json_object_get_int64(value) : fallback;
}

json_object *parse_json(const char *data, size_t len) {
    if (!data || !len || len > MAX_MESSAGE) return NULL;
    struct json_tokener *parser = json_tokener_new_ex(24);
    if (!parser) return NULL;
    json_tokener_set_flags(parser, JSON_TOKENER_STRICT | JSON_TOKENER_VALIDATE_UTF8);
    json_object *result = json_tokener_parse_ex(parser,data,(int)len);
    if (json_tokener_get_error(parser) != json_tokener_success || !json_object_is_type(result,json_type_object)) {
        json_object_put(result); result = NULL;
    }
    json_tokener_free(parser);
    return result;
}

char *encode64(const unsigned char *data, size_t len) {
    size_t size = sodium_base64_ENCODED_LEN(len,sodium_base64_VARIANT_ORIGINAL);
    char *out = malloc(size);
    return out ? sodium_bin2base64(out,size,data,len,sodium_base64_VARIANT_ORIGINAL) : NULL;
}

int decode64(const char *s, unsigned char *out, size_t length) {
    size_t written = 0;
    if (!s || strlen(s) != sodium_base64_ENCODED_LEN(length,sodium_base64_VARIANT_ORIGINAL)-1) return -1;
    return sodium_base642bin(out,length,s,strlen(s),NULL,&written,NULL,sodium_base64_VARIANT_ORIGINAL) || written != length ? -1 : 0;
}

json_object *failure(int status, const char *message) {
    json_object *obj = json_object_new_object();
    json_object_object_add(obj,"status",json_object_new_int(status));
    json_object_object_add(obj,"error",json_object_new_string(message));
    return obj;
}

json_object *success(json_object *data) {
    json_object *obj = json_object_new_object();
    json_object_object_add(obj,"status",json_object_new_int(200));
    json_object_object_add(obj,"data",data ? data : json_object_new_object());
    return obj;
}

static bool valid_id(const char *id) {
    if (!id || strlen(id) != 36) return false;
    for (int i=0;i<36;i++) {
        if (i==8 || i==13 || i==18 || i==23) { if(id[i]!='-') return false; }
        else if (!((id[i]>='0' && id[i]<='9') || (id[i]>='a' && id[i]<='f'))) return false;
    }
    return true;
}

static int consume_id(sqlite3 *db, const char *id, int64_t now) {
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db,"DELETE FROM replays WHERE expires<?",-1,&stmt,NULL) != SQLITE_OK) return -1;
    sqlite3_bind_int64(stmt,1,now); sqlite3_step(stmt); sqlite3_finalize(stmt);
    if (sqlite3_prepare_v2(db,"INSERT INTO replays(id,expires) SELECT ?,? WHERE (SELECT COUNT(*) FROM replays)<4096",-1,&stmt,NULL) != SQLITE_OK) return -1;
    sqlite3_bind_text(stmt,1,id,-1,SQLITE_TRANSIENT); sqlite3_bind_int64(stmt,2,now+240);
    int ok = sqlite3_step(stmt)==SQLITE_DONE && sqlite3_changes(db)==1;
    sqlite3_finalize(stmt);
    return ok ? 0 : -1;
}

static bool authenticated(sqlite3 *db, const char *token) {
    unsigned char raw[32], hash[32];
    if (decode64(token,raw,sizeof(raw))) return false;
    crypto_generichash(hash,sizeof(hash),raw,sizeof(raw),NULL,0); sodium_memzero(raw,sizeof(raw));
    sqlite3_stmt *stmt = NULL;
    bool ok = false;
    if (sqlite3_prepare_v2(db,"SELECT 1 FROM sessions WHERE hash=? AND expires>?",-1,&stmt,NULL)==SQLITE_OK) {
        sqlite3_bind_blob(stmt,1,hash,sizeof(hash),SQLITE_TRANSIENT); sqlite3_bind_int64(stmt,2,(int64_t)time(NULL));
        ok = sqlite3_step(stmt)==SQLITE_ROW;
    }
    sqlite3_finalize(stmt);
    return ok;
}

static bool valid_record(const char *record) {
    if (!record || strlen(record)>MAX_ITEM) return false;
    json_object *obj = parse_json(record,strlen(record));
    unsigned char nonce[crypto_secretbox_NONCEBYTES];
    const char *box = jstr(obj,"box",MAX_ITEM);
    bool ok = jint(obj,"v",0)==1 && !decode64(jstr(obj,"nonce",64),nonce,sizeof(nonce)) && box && strlen(box)>=24;
    if (ok) {
        size_t len=0;
        unsigned char *decoded=malloc(strlen(box));
        ok = decoded && !sodium_base642bin(decoded,strlen(box),box,strlen(box),NULL,&len,NULL,sodium_base64_VARIANT_ORIGINAL) && len>=crypto_secretbox_MACBYTES;
        free(decoded);
    }
    json_object_put(obj);
    return ok;
}

static json_object *configuration(sqlite3 *db) {
    char *salt=meta_get(db,"salt"), *enrollment=meta_get(db,"enrollment");
    if (!salt || !enrollment) { free(salt); free(enrollment); return failure(500,"Server configuration unavailable."); }
    json_object *obj=json_object_new_object();
    json_object_object_add(obj,"salt",json_object_new_string(salt));
    json_object_object_add(obj,"iterations",json_object_new_int(3));
    json_object_object_add(obj,"memoryKiB",json_object_new_int(65536));
    json_object_object_add(obj,"parallelism",json_object_new_int(1));
    json_object_object_add(obj,"enrollmentOpen",json_object_new_boolean(strlen(enrollment)>0));
    free(salt); free(enrollment);
    return success(obj);
}

static json_object *sign_in(struct server *server, json_object *data, bool enrollment) {
    sqlite3 *db=server->db;
    int64_t now=(int64_t)time(NULL);
    if (now-server->login_window>=60) { server->login_window=now; server->login_attempts=0; }
    if (server->login_attempts>=5) return failure(429,"Too many attempts. Try again in a minute.");
    server->login_attempts++;
    const char *email=jstr(data,"email",254), *auth=jstr(data,"authKey",64), *wrapped=jstr(data,"wrappedKey",2048);
    unsigned char key[32];
    char *owner=meta_get(db,"owner");
    bool accepted=email && owner && !strcmp(email,owner) && !decode64(auth,key,sizeof(key));
    free(owner);
    sqlite3_stmt *stmt=NULL;
    if (!accepted) return failure(401,"Sign-in rejected.");
    if (enrollment) {
        unsigned char token[32], hash[32], expected[32];
        char *stored=meta_get(db,"enrollment");
        const char *provided=jstr(data,"enrollmentToken",64);
        accepted=stored && !decode64(stored,expected,sizeof(expected)) && !decode64(provided,token,sizeof(token)) && valid_record(wrapped);
        if (accepted) {
            crypto_generichash(hash,sizeof(hash),token,sizeof(token),NULL,0);
            accepted=sodium_memcmp(hash,expected,sizeof(hash))==0;
        }
        sodium_memzero(token,sizeof(token)); free(stored);
        if (accepted) {
            char verifier[crypto_pwhash_STRBYTES];
            if (crypto_pwhash_str_alg(verifier,(const char *)key,sizeof(key),crypto_pwhash_OPSLIMIT_INTERACTIVE,crypto_pwhash_MEMLIMIT_INTERACTIVE,crypto_pwhash_ALG_ARGON2ID13)) {
                sodium_memzero(key,sizeof(key)); return failure(503,"Authentication is temporarily unavailable.");
            }
            if (exec_sql(db,"BEGIN IMMEDIATE")) accepted=false;
            if (accepted && sqlite3_prepare_v2(db,"INSERT INTO owner(id,email,verifier,wrapped) VALUES(1,?,?,?)",-1,&stmt,NULL)==SQLITE_OK) {
                sqlite3_bind_text(stmt,1,email,-1,SQLITE_TRANSIENT); sqlite3_bind_text(stmt,2,verifier,-1,SQLITE_TRANSIENT); sqlite3_bind_text(stmt,3,wrapped,-1,SQLITE_TRANSIENT);
                accepted=sqlite3_step(stmt)==SQLITE_DONE;
            } else accepted=false;
            sqlite3_finalize(stmt); stmt=NULL;
            if (accepted) accepted=!meta_set(db,"enrollment","") && !exec_sql(db,"COMMIT");
            if (!accepted) exec_sql(db,"ROLLBACK");
            sodium_memzero(verifier,sizeof(verifier));
        }
    } else {
        accepted=false;
        if (sqlite3_prepare_v2(db,"SELECT verifier FROM owner WHERE id=1",-1,&stmt,NULL)==SQLITE_OK && sqlite3_step(stmt)==SQLITE_ROW) {
            accepted=crypto_pwhash_str_verify((const char *)sqlite3_column_text(stmt,0),(const char *)key,sizeof(key))==0;
        }
        sqlite3_finalize(stmt); stmt=NULL;
    }
    sodium_memzero(key,sizeof(key));
    if (!accepted) return failure(401,"Sign-in rejected.");
    server->login_attempts=0;
    unsigned char token[32], hash[32];
    randombytes_buf(token,sizeof(token)); crypto_generichash(hash,sizeof(hash),token,sizeof(token),NULL,0);
    char *token64=encode64(token,sizeof(token)); sodium_memzero(token,sizeof(token));
    if (!token64) return failure(500,"Session unavailable.");
    if (sqlite3_prepare_v2(db,"DELETE FROM sessions WHERE expires<=?",-1,&stmt,NULL)==SQLITE_OK) {
        sqlite3_bind_int64(stmt,1,now); sqlite3_step(stmt);
    }
    sqlite3_finalize(stmt); stmt=NULL;
    bool ok=false;
    if (sqlite3_prepare_v2(db,"INSERT INTO sessions(hash,expires) SELECT ?,? WHERE (SELECT COUNT(*) FROM sessions)<64",-1,&stmt,NULL)==SQLITE_OK) {
        sqlite3_bind_blob(stmt,1,hash,sizeof(hash),SQLITE_TRANSIENT); sqlite3_bind_int64(stmt,2,now+SESSION_SECONDS);
        ok=sqlite3_step(stmt)==SQLITE_DONE && sqlite3_changes(db)==1;
    }
    sqlite3_finalize(stmt); stmt=NULL;
    if (!ok) { sodium_memzero(token64,strlen(token64)); free(token64); return failure(503,"Session limit reached. Try again shortly."); }
    json_object *obj=json_object_new_object();
    json_object_object_add(obj,"token",json_object_new_string(token64));
    json_object_object_add(obj,"expiresAt",json_object_new_int64(now+SESSION_SECONDS));
    if (sqlite3_prepare_v2(db,"SELECT wrapped FROM owner WHERE id=1",-1,&stmt,NULL)==SQLITE_OK && sqlite3_step(stmt)==SQLITE_ROW)
        json_object_object_add(obj,"wrappedKey",json_object_new_string((const char *)sqlite3_column_text(stmt,0)));
    sqlite3_finalize(stmt);
    sodium_memzero(token64,strlen(token64)); free(token64);
    return success(obj);
}

static json_object *sync_items(sqlite3 *db, json_object *request) {
    const char *after=jstr(request,"after",36);
    if (after && !valid_id(after)) return failure(400,"Invalid sync cursor.");
    sqlite3_stmt *stmt=NULL;
    json_object *items=json_object_new_array(), *data=json_object_new_object();
    if (sqlite3_prepare_v2(db,"SELECT id,revision,deleted,payload FROM items WHERE id>? ORDER BY id LIMIT 33",-1,&stmt,NULL)!=SQLITE_OK) {
        json_object_put(items); json_object_put(data); return failure(500,"Sync unavailable.");
    }
    sqlite3_bind_text(stmt,1,after ? after : "",-1,SQLITE_TRANSIENT);
    int step, count=0;
    char cursor[37]={0};
    while ((step=sqlite3_step(stmt))==SQLITE_ROW) {
        if(count==32) break;
        const char *id=(const char *)sqlite3_column_text(stmt,0);
        if(strlen(id)!=36) { step=SQLITE_CORRUPT; break; }
        memcpy(cursor,id,37); count++;
        json_object *item=json_object_new_object();
        json_object_object_add(item,"id",json_object_new_string((const char *)sqlite3_column_text(stmt,0)));
        json_object_object_add(item,"revision",json_object_new_int64(sqlite3_column_int64(stmt,1)));
        json_object_object_add(item,"deleted",json_object_new_boolean(sqlite3_column_int(stmt,2)));
        json_object_object_add(item,"payload",json_object_new_string((const char *)sqlite3_column_text(stmt,3)));
        json_object_array_add(items,item);
    }
    sqlite3_finalize(stmt);
    if (step!=SQLITE_DONE && step!=SQLITE_ROW) { json_object_put(items); json_object_put(data); return failure(500,"Sync unavailable."); }
    json_object_object_add(data,"items",items);
    json_object_object_add(data,"cursor",step==SQLITE_ROW ? json_object_new_string(cursor) : NULL);
    return success(data);
}

static json_object *write_item(sqlite3 *db, json_object *data, bool deleting) {
    const char *id=jstr(data,"id",36), *payload=jstr(data,"payload",MAX_ITEM);
    int64_t expected=jint(data,"revision",-1);
    if (!valid_id(id) || expected<0 || (!deleting && !valid_record(payload))) return failure(400,"Invalid encrypted item.");
    if (exec_sql(db,"BEGIN IMMEDIATE")) return failure(503,"Vault is busy.");
    sqlite3_stmt *stmt=NULL;
    int64_t current=0;
    bool exists=false, deleted=false, ok=false;
    if (sqlite3_prepare_v2(db,"SELECT revision,deleted FROM items WHERE id=?",-1,&stmt,NULL)==SQLITE_OK) {
        sqlite3_bind_text(stmt,1,id,-1,SQLITE_TRANSIENT);
        if (sqlite3_step(stmt)==SQLITE_ROW) { current=sqlite3_column_int64(stmt,0); deleted=sqlite3_column_int(stmt,1)!=0; exists=true; }
    }
    sqlite3_finalize(stmt); stmt=NULL;
    if (expected!=current || (deleting && (!exists || deleted)) || (!deleting && deleted)) {
        exec_sql(db,"ROLLBACK"); return failure(409,"This login changed on another client. Sync before trying again.");
    }
    if(!deleting) {
        bool capacity=false;
        if(sqlite3_prepare_v2(db,"SELECT COUNT(*),COALESCE(SUM(length(payload)),0)-COALESCE((SELECT length(payload) FROM items WHERE id=?),0) FROM items",-1,&stmt,NULL)==SQLITE_OK) {
            sqlite3_bind_text(stmt,1,id,-1,SQLITE_TRANSIENT);
            if(sqlite3_step(stmt)==SQLITE_ROW) capacity=(exists || sqlite3_column_int(stmt,0)<4096) && sqlite3_column_int64(stmt,1)+(int64_t)strlen(payload)<=64*1024*1024;
        }
        sqlite3_finalize(stmt); stmt=NULL;
        if(!capacity) { exec_sql(db,"ROLLBACK"); return failure(413,"Vault storage limit reached."); }
    }
    char *revision_text=meta_get(db,"revision");
    int64_t revision=revision_text ? strtoll(revision_text,NULL,10) : -1;
    free(revision_text);
    if (revision<0 || revision>=INT64_MAX-1) { exec_sql(db,"ROLLBACK"); return failure(500,"Revision unavailable."); }
    revision++;
    const char *sql=deleting ? "UPDATE items SET revision=?,deleted=1,payload='' WHERE id=?" : "INSERT INTO items(revision,id,payload,deleted) VALUES(?,?,?,0) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload";
    if (sqlite3_prepare_v2(db,sql,-1,&stmt,NULL)==SQLITE_OK) {
        sqlite3_bind_int64(stmt,1,revision); sqlite3_bind_text(stmt,2,id,-1,SQLITE_TRANSIENT);
        if (!deleting) sqlite3_bind_text(stmt,3,payload,-1,SQLITE_TRANSIENT);
        ok=sqlite3_step(stmt)==SQLITE_DONE;
    }
    sqlite3_finalize(stmt);
    char next[32]; snprintf(next,sizeof(next),"%lld",(long long)revision);
    if (ok) ok=!meta_set(db,"revision",next) && !exec_sql(db,"COMMIT");
    if (!ok) { exec_sql(db,"ROLLBACK"); return failure(500,"Could not save the login."); }
    json_object *obj=json_object_new_object();
    json_object_object_add(obj,"revision",json_object_new_int64(revision));
    return success(obj);
}

json_object *dispatch(struct server *server, json_object *request) {
    const char *action=jstr(request,"action",32), *token=jstr(request,"token",64);
    json_object *data=NULL;
    json_object_object_get_ex(request,"data",&data);
    if (!action || !json_object_is_type(data,json_type_object)) return failure(400,"Invalid request.");
    if (!strcmp(action,"config")) return configuration(server->db);
    if (!strcmp(action,"enroll") || !strcmp(action,"login")) return sign_in(server,data,!strcmp(action,"enroll"));
    if (!authenticated(server->db,token)) return failure(401,"Vault is locked. Sign in again.");
    if (!strcmp(action,"sync")) return sync_items(server->db,data);
    if (!strcmp(action,"put") || !strcmp(action,"delete")) return write_item(server->db,data,!strcmp(action,"delete"));
    if (!strcmp(action,"logout")) {
        unsigned char raw[32], hash[32];
        if (decode64(token,raw,sizeof(raw))) return failure(400,"Invalid token.");
        crypto_generichash(hash,sizeof(hash),raw,sizeof(raw),NULL,0); sodium_memzero(raw,sizeof(raw));
        sqlite3_stmt *stmt=NULL;
        if (sqlite3_prepare_v2(server->db,"DELETE FROM sessions WHERE hash=?",-1,&stmt,NULL)==SQLITE_OK) {
            sqlite3_bind_blob(stmt,1,hash,sizeof(hash),SQLITE_TRANSIENT); sqlite3_step(stmt);
        }
        sqlite3_finalize(stmt); return success(NULL);
    }
    return failure(404,"Unknown operation.");
}

json_object *exchange(struct server *server, json_object *envelope) {
    unsigned char pk[crypto_box_PUBLICKEYBYTES], nonce[crypto_box_NONCEBYTES];
    const char *box=jstr(envelope,"box",MAX_MESSAGE);
    if (jint(envelope,"v",0)!=1 || decode64(jstr(envelope,"key",64),pk,sizeof(pk)) || decode64(jstr(envelope,"nonce",64),nonce,sizeof(nonce)) || !box) return NULL;
    size_t capacity=strlen(box), size=0;
    unsigned char *cipher=malloc(capacity), *plain=calloc(capacity+1,1);
    json_object *request=NULL, *reply=NULL, *result=NULL;
    if (!cipher || !plain || sodium_base642bin(cipher,capacity,box,capacity,NULL,&size,NULL,sodium_base64_VARIANT_ORIGINAL) || size<crypto_box_MACBYTES || crypto_box_open_easy(plain,cipher,size,nonce,pk,server->sk)) goto done;
    request=parse_json((const char *)plain,size-crypto_box_MACBYTES);
    const char *id=jstr(request,"id",36), *direction=jstr(request,"direction",16);
    int64_t now=(int64_t)time(NULL), issued=jint(request,"issuedAt",0);
    if (!valid_id(id) || !direction || strcmp(direction,"request") || jint(request,"v",0)!=1) goto done;
    if (issued<now-120 || issued>now+120) reply=failure(408,"Check your device clock and try again.");
    else if (consume_id(server->db,id,now)) reply=failure(409,"Request already used or server busy. Try again.");
    else reply=dispatch(server,request);
    json_object_object_add(reply,"id",json_object_new_string(id));
    json_object_object_add(reply,"v",json_object_new_int(1));
    json_object_object_add(reply,"direction",json_object_new_string("response"));
    const char *serialized=json_object_to_json_string_ext(reply,JSON_C_TO_STRING_PLAIN);
    size_t length=strlen(serialized);
    unsigned char *encrypted=malloc(length+crypto_box_MACBYTES);
    if (!encrypted) goto done;
    randombytes_buf(nonce,sizeof(nonce));
    if (crypto_box_easy(encrypted,(const unsigned char *)serialized,length,nonce,pk,server->sk)) { free(encrypted); goto done; }
    char *encoded=encode64(encrypted,length+crypto_box_MACBYTES), *nonce64=encode64(nonce,sizeof(nonce));
    free(encrypted);
    if (encoded && nonce64) {
        result=json_object_new_object();
        json_object_object_add(result,"v",json_object_new_int(1));
        json_object_object_add(result,"nonce",json_object_new_string(nonce64));
        json_object_object_add(result,"box",json_object_new_string(encoded));
    }
    free(encoded); free(nonce64);
done:
    if (plain) sodium_memzero(plain,capacity+1);
    free(cipher); free(plain);
    if (request) { const char *s=json_object_to_json_string_ext(request,JSON_C_TO_STRING_PLAIN); sodium_memzero((void *)s,strlen(s)); }
    json_object_put(request); json_object_put(reply);
    return result;
}

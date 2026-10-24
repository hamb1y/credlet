#define _POSIX_C_SOURCE 200809L
#include "credlet.h"
#include <event2/buffer.h>
#include <event2/event.h>
#include <event2/http.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <winsock2.h>
#endif

static void stop_server(evutil_socket_t fd, short events, void *context) {
    (void)fd; (void)events;
    event_base_loopbreak(context);
}

static void http_request(struct evhttp_request *request, void *context) {
    struct server *server=context;
    const char *uri=evhttp_request_get_uri(request);
    struct evkeyvalq *headers=evhttp_request_get_output_headers(request);
    evhttp_add_header(headers,"Content-Type","application/json");
    evhttp_add_header(headers,"Cache-Control","no-store");
    evhttp_add_header(headers,"X-Content-Type-Options","nosniff");
    struct evbuffer *output=evbuffer_new();
    if (!output) { evhttp_send_error(request,503,"Unavailable"); return; }
    int status=400;
    json_object *envelope=NULL, *response=NULL;
    if (evhttp_request_get_command(request)==EVHTTP_REQ_GET && !strcmp(uri,"/health")) {
        status=204;
    } else if (evhttp_request_get_command(request)==EVHTTP_REQ_POST && !strcmp(uri,"/v1/exchange")) {
        struct evbuffer *input=evhttp_request_get_input_buffer(request);
        size_t size=evbuffer_get_length(input);
        if (size && size<=MAX_MESSAGE) envelope=parse_json((const char *)evbuffer_pullup(input,-1),size);
        if (envelope) response=exchange(server,envelope);
        if (response) {
            const char *body=json_object_to_json_string_ext(response,JSON_C_TO_STRING_PLAIN);
            evbuffer_add(output,body,strlen(body)); status=200;
        }
    } else status=404;
    evhttp_send_reply(request,status,NULL,output);
    evbuffer_free(output); json_object_put(envelope); json_object_put(response);
}

int serve(struct server *server, const char *address, unsigned short port) {
    struct event_base *base=event_base_new();
    if (!base) return -1;
    struct evhttp *http=evhttp_new(base);
    if (!http) { event_base_free(base); return -1; }
    evhttp_set_max_body_size(http,MAX_MESSAGE);
    evhttp_set_max_headers_size(http,8192);
    evhttp_set_timeout(http,15);
    evhttp_set_allowed_methods(http,EVHTTP_REQ_GET|EVHTTP_REQ_POST);
    evhttp_set_gencb(http,http_request,server);
    if (evhttp_bind_socket(http,address,port)) { evhttp_free(http); event_base_free(base); return -1; }
    struct event *interrupt=evsignal_new(base,SIGINT,stop_server,base);
    struct event *terminate=evsignal_new(base,SIGTERM,stop_server,base);
    if (interrupt) event_add(interrupt,NULL);
    if (terminate) event_add(terminate,NULL);
    fprintf(stderr,"Credlet %s listening on http://%s:%u (application-encrypted protocol)\n",CREDLET_VERSION,address,port);
    event_base_dispatch(base);
    event_free(interrupt); event_free(terminate); evhttp_free(http); event_base_free(base);
    return 0;
}

int main(int argc, char **argv) {
    if (sodium_init()<0) return 1;
#ifdef _WIN32
    WSADATA data;
    if (WSAStartup(MAKEWORD(2,2),&data)) return 1;
#endif
    if (argc<2 || !strcmp(argv[1],"--help")) {
        puts("Credlet C server " CREDLET_VERSION "\nUsage: credlet-server init|pair|serve|backup|restore --state DIR [--owner EMAIL] [--listen ADDRESS] [--port PORT] [--output FILE] [--input FILE]");
        return argc<2 ? 1 : 0;
    }
    const char *state="state-v3", *owner=NULL, *address="127.0.0.1", *output=NULL, *input=NULL;
    unsigned short port=8223;
    for (int i=2;i<argc;i+=2) {
        if (i+1>=argc) { fputs("Missing option value.\n",stderr); return 1; }
        if (!strcmp(argv[i],"--state")) state=argv[i+1];
        else if (!strcmp(argv[i],"--owner")) owner=argv[i+1];
        else if (!strcmp(argv[i],"--listen")) address=argv[i+1];
        else if (!strcmp(argv[i],"--output")) output=argv[i+1];
        else if (!strcmp(argv[i],"--input")) input=argv[i+1];
        else if (!strcmp(argv[i],"--port")) {
            char *end=NULL; long value=strtol(argv[i+1],&end,10);
            if (!end || *end || value<1 || value>65535) { fputs("Invalid port.\n",stderr); return 1; }
            port=(unsigned short)value;
        } else { fputs("Unknown option.\n",stderr); return 1; }
    }
    bool init=!strcmp(argv[1],"init");
    bool restore=!strcmp(argv[1],"restore");
    if (strcmp(argv[1],"serve") && strcmp(argv[1],"pair") && strcmp(argv[1],"backup") && !init && !restore) { fputs("Unknown command.\n",stderr); return 1; }
    if((restore && !input) || (!strcmp(argv[1],"backup") && !output)) { fputs("Specify --input for restore or --output for backup.\n",stderr); return 1; }
    if (init && (!owner || strlen(owner)>254 || !strchr(owner,'@') || strchr(owner,'\n') || strchr(owner,' '))) { fputs("init requires a valid lowercase owner email.\n",stderr); return 1; }
    if (owner) for (const char *p=owner;*p;p++) if (*p>='A' && *p<='Z') { fputs("Use a lowercase owner email.\n",stderr); return 1; }
    struct server server={0};
    if (store_open(&server,state,init||restore)) { fputs("Cannot open private state; init/restore requires a new database and serve requires initialized state.\n",stderr); store_close(&server); return 1; }
    int result=init ? store_init(&server,owner) : restore ? store_restore(&server,input) : !strcmp(argv[1],"pair") ? print_pairing(&server) : !strcmp(argv[1],"backup") ? store_backup(&server,output) : serve(&server,address,port);
    store_close(&server);
    if (result) fputs("Operation failed; existing vault state was preserved.\n",stderr);
    return result ? 1 : 0;
}

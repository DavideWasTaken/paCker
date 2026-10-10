#include "oblique.h"
#include "json3d.h"
#include "../third_party/cJSON.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#include <shellapi.h>
#endif

#define INPUT_LIMIT (1024u * 1024u)
#define JSON_DEPTH_LIMIT 16

/* cJSON deliberately accepts some non-JSON numbers and does not validate UTF-8.
 * Validate the complete byte stream before letting it create the parse tree. */
typedef struct { const unsigned char *p, *end; } Scanner;
static void whitespace(Scanner *s) {
    while (s->p < s->end && (*s->p == ' ' || *s->p == '\t' || *s->p == '\n' || *s->p == '\r')) ++s->p;
}
static int digit(unsigned char c) { return c >= '0' && c <= '9'; }
static int hex4(Scanner *s, unsigned *out) {
    unsigned v = 0;
    if (s->end - s->p < 4) return 0;
    for (int i = 0; i < 4; ++i) {
        unsigned c = *s->p++, n;
        if (c >= '0' && c <= '9') n = c - '0';
        else if (c >= 'a' && c <= 'f') n = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') n = c - 'A' + 10;
        else return 0;
        v = v * 16 + n;
    }
    *out = v; return 1;
}
static int json_string(Scanner *s) {
    if (s->p == s->end || *s->p++ != '"') return 0;
    while (s->p < s->end) {
        unsigned c = *s->p++;
        if (c == '"') return 1;
        if (c < 32) return 0;
        if (c == '\\') {
            if (s->p == s->end) return 0;
            c = *s->p++;
            if (c == 'u') {
                unsigned u;
                if (!hex4(s, &u) || u == 0) return 0; /* cJSON uses NUL-terminated strings. */
                if (u >= 0xd800 && u <= 0xdbff) {
                    unsigned low;
                    if (s->end - s->p < 6 || *s->p++ != '\\' || *s->p++ != 'u' ||
                        !hex4(s, &low) || low < 0xdc00 || low > 0xdfff) return 0;
                } else if (u >= 0xdc00 && u <= 0xdfff) return 0;
            } else if (!strchr("\"\\/bfnrt", (int)c) || c == 0) return 0;
        } else if (c >= 128) {
            unsigned code, minimum; int count;
            if (c >= 0xc2 && c <= 0xdf) { code = c & 31; count = 1; minimum = 0x80; }
            else if (c >= 0xe0 && c <= 0xef) { code = c & 15; count = 2; minimum = 0x800; }
            else if (c >= 0xf0 && c <= 0xf4) { code = c & 7; count = 3; minimum = 0x10000; }
            else return 0;
            if (s->end - s->p < count) return 0;
            while (count--) {
                c = *s->p++;
                if ((c & 0xc0) != 0x80) return 0;
                code = (code << 6) | (c & 63);
            }
            if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return 0;
        }
    }
    return 0;
}
static int json_number(Scanner *s) {
    if (s->p < s->end && *s->p == '-') ++s->p;
    if (s->p == s->end || !digit(*s->p)) return 0;
    if (*s->p == '0') ++s->p;
    else while (s->p < s->end && digit(*s->p)) ++s->p;
    if (s->p < s->end && *s->p == '.') {
        ++s->p;
        if (s->p == s->end || !digit(*s->p)) return 0;
        while (s->p < s->end && digit(*s->p)) ++s->p;
    }
    if (s->p < s->end && (*s->p == 'e' || *s->p == 'E')) {
        ++s->p;
        if (s->p < s->end && (*s->p == '+' || *s->p == '-')) ++s->p;
        if (s->p == s->end || !digit(*s->p)) return 0;
        while (s->p < s->end && digit(*s->p)) ++s->p;
    }
    return 1;
}
static int json_value(Scanner *s, int depth) {
    whitespace(s);
    if (depth > JSON_DEPTH_LIMIT || s->p == s->end) return 0;
    unsigned c = *s->p;
    if (c == '"') return json_string(s);
    if (c == '[' || c == '{') {
        const unsigned close = c == '[' ? ']' : '}';
        ++s->p; whitespace(s);
        if (s->p < s->end && *s->p == close) { ++s->p; return 1; }
        for (;;) {
            if (c == '{') {
                if (!json_string(s)) return 0;
                whitespace(s);
                if (s->p == s->end || *s->p++ != ':') return 0;
            }
            if (!json_value(s, depth + 1)) return 0;
            whitespace(s);
            if (s->p == s->end) return 0;
            if (*s->p == close) { ++s->p; return 1; }
            if (*s->p++ != ',') return 0;
            whitespace(s);
        }
    }
    const char *literal = c == 't' ? "true" : c == 'f' ? "false" : c == 'n' ? "null" : NULL;
    if (literal) {
        size_t n = strlen(literal);
        if ((size_t)(s->end - s->p) < n || memcmp(s->p, literal, n)) return 0;
        s->p += n; return 1;
    }
    return json_number(s);
}
static int fail(char *error, const char *message) { snprintf(error, 256, "%s", message); return 0; }
static int fields(const cJSON *object, const char *const *allowed, char *error) {
    if (!cJSON_IsObject(object)) return fail(error, "Expected a JSON object");
    for (const cJSON *p = object->child; p; p = p->next) {
        int found = 0;
        for (int i = 0; allowed[i]; ++i) if (!strcmp(p->string, allowed[i])) { found = 1; break; }
        if (!found) { snprintf(error, 256, "Unknown member: %.100s", p->string); return 0; }
        for (const cJSON *q = object->child; q != p; q = q->next)
            if (!strcmp(p->string, q->string)) return fail(error, "Duplicate object member");
    }
    return 1;
}
static const cJSON *member(const cJSON *object, const char *key) { return cJSON_GetObjectItemCaseSensitive(object, key); }
static int number(const cJSON *object, const char *key, double low, double high,
                  int integer, int required, double fallback, double *out, char *error) {
    const cJSON *v = member(object, key);
    if (!v && !required) { *out = fallback; return 1; }
    if (!cJSON_IsNumber(v) || !isfinite(v->valuedouble) || v->valuedouble < low ||
        v->valuedouble > high || (integer && floor(v->valuedouble) != v->valuedouble)) {
        snprintf(error, 256, "Invalid or missing numeric member: %s", key); return 0;
    }
    *out = v->valuedouble; return 1;
}
static int identity(const cJSON *object, char *id, char *error) {
    const cJSON *v = member(object, "id");
    if (!cJSON_IsString(v) || !*v->valuestring || strlen(v->valuestring) >= OP_ID_SIZE)
        return fail(error, "id must contain 1..63 UTF-8 bytes");
    strcpy(id, v->valuestring); return 1;
}
#define NUM(obj,key,lo,hi,integer,required,def,out) \
    do { if (!number(obj,key,lo,hi,integer,required,def,out,error)) return 0; } while(0)
#define DIM(obj,key,out) NUM(obj,key,0.0001,1000000,0,1,0,out)
static int request_from_json(const cJSON *root, OpRequest *request, char *error) {
    static const char *const root_fields[] = {"boxes", "items", "options", NULL};
    static const char *const box_fields[] = {"id", "width", "length", "height", "max_weight", "cost", "quantity", NULL};
    static const char *const item_fields[] = {"id", "width", "length", "height", "weight", "quantity", "rotation", "diagonal", NULL};
    static const char *const option_fields[] = {"angle_step", "restarts", "max_candidates", "time_limit_ms", "seed", "gap", "support_mode", "improve", NULL};
    if (!fields(root, root_fields, error)) return 0;
    const cJSON *boxes = member(root, "boxes"), *items = member(root, "items"), *options = member(root, "options");
    if (!cJSON_IsArray(boxes) || !cJSON_IsArray(items)) return fail(error, "boxes and items arrays are required");
    if (cJSON_GetArraySize(boxes) > OP_MAX_BOXES || cJSON_GetArraySize(items) > OP_MAX_ITEMS)
        return fail(error, "Limit exceeded: 64 box types, 256 expanded items");
    memset(request, 0, sizeof *request);
    op_default_options(&request->options);
    for (const cJSON *p = boxes->child; p; p = p->next) {
        OpBox *b = &request->boxes[request->box_count]; double quantity;
        if (!fields(p, box_fields, error) || !identity(p, b->id, error)) return 0;
        for (int i = 0; i < request->box_count; ++i)
            if (!strcmp(b->id, request->boxes[i].id)) return fail(error, "Duplicate box id");
        DIM(p,"width",&b->width); DIM(p,"length",&b->length); DIM(p,"height",&b->height);
        NUM(p,"max_weight",0,1e12,0,0,1e12,&b->max_weight);
        NUM(p,"cost",0,1e12,0,0,1,&b->cost);
        NUM(p,"quantity",-1,256,1,0,-1,&quantity); b->quantity = (int)quantity;
        ++request->box_count;
    }
    for (const cJSON *p = items->child; p; p = p->next) {
        OpItem item = {0}; double quantity;
        if (!fields(p, item_fields, error) || !identity(p, item.id, error)) return 0;
        for (int i = 0; i < request->item_count; ++i)
            if (!strcmp(item.id, request->items[i].id)) return fail(error, "Duplicate item id");
        DIM(p,"width",&item.width); DIM(p,"length",&item.length); DIM(p,"height",&item.height);
        NUM(p,"weight",0,1e12,0,0,0,&item.weight);
        NUM(p,"quantity",1,256,1,0,1,&quantity);
        if (request->item_count + (int)quantity > OP_MAX_ITEMS) return fail(error, "Limit exceeded: 256 expanded items");
        item.rotation = OP_FLAT; item.diagonal = 1;
        const cJSON *rotation = member(p,"rotation"), *diagonal = member(p,"diagonal");
        if (rotation) {
            if (!cJSON_IsString(rotation)) return fail(error, "rotation must be none, flat, or any");
            if (!strcmp(rotation->valuestring,"none")) item.rotation = OP_NONE;
            else if (!strcmp(rotation->valuestring,"flat")) item.rotation = OP_FLAT;
            else if (!strcmp(rotation->valuestring,"any")) item.rotation = OP_ANY;
            else if (!strcmp(rotation->valuestring,"free3d")) return fail(error, "free3d requires support_mode geometric");
            else return fail(error, "rotation must be none, flat, or any");
        }
        if (diagonal) {
            if (!cJSON_IsBool(diagonal)) return fail(error,"diagonal must be boolean");
            item.diagonal = cJSON_IsTrue(diagonal);
        }
        for (int i = 0; i < (int)quantity; ++i) {
            item.instance = i; request->items[request->item_count++] = item;
        }
    }
    if (options) {
        if (!fields(options, option_fields, error)) return 0;
        OpOptions *o = &request->options; double value;
        NUM(options,"angle_step",1,90,1,0,o->angle_step,&o->angle_step);
        NUM(options,"time_limit_ms",1,60000,0,0,o->time_limit_ms,&o->time_limit_ms);
        NUM(options,"gap",0,1e6,0,0,o->gap,&o->gap);
        NUM(options,"restarts",1,64,1,0,o->restarts,&value); o->restarts = (int)value;
        NUM(options,"seed",0,4294967295.0,1,0,o->seed,&value); o->seed = (unsigned)value;
        NUM(options,"max_candidates",1,100000000,1,0,(double)o->max_candidates,&value); o->max_candidates = (uint64_t)value;
        const cJSON *mode = member(options,"support_mode"), *improve = member(options,"improve");
        if (mode) o->support = strcmp(mode->valuestring,"full_base") ? OP_SUPPORT_CONTACT : OP_SUPPORT_FULL_BASE;
        if (improve) {
            if (!cJSON_IsBool(improve)) return fail(error,"improve must be boolean");
            o->improve = cJSON_IsTrue(improve);
        }
    }
    return 1;
}

/* All response allocation failures unwind the tree without emitting a partial document. */
#define ADD_NUM(obj,key,val) do { if (!cJSON_AddNumberToObject(obj,key,(double)(val))) goto oom; } while(0)
#define ADD_STR(obj,key,val) do { if (!cJSON_AddStringToObject(obj,key,val)) goto oom; } while(0)
#define ADD_BOOL(obj,key,val) do { if (!cJSON_AddBoolToObject(obj,key,val)) goto oom; } while(0)
static cJSON *array_object(cJSON *array) {
    cJSON *child = cJSON_CreateObject();
    if (child && !cJSON_AddItemToArray(array, child)) { cJSON_Delete(child); return NULL; }
    return child;
}
static cJSON *result_to_json(const OpRequest *request, const OpResult *result) {
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    ADD_STR(root,"version",OP_VERSION);
    ADD_STR(root,"support_mode",request->options.support == OP_SUPPORT_FULL_BASE ? "full_base" : "contact");
    ADD_STR(root,"status",result->unpacked_count ? "partial" : "complete");
    cJSON *bins = cJSON_AddArrayToObject(root,"bins"), *unpacked = cJSON_AddArrayToObject(root,"unpacked");
    if (!bins || !unpacked) goto oom;
    for (int i = 0; i < result->bin_count; ++i) {
        const OpBin *bin = &result->bins[i]; const OpBox *box = &request->boxes[bin->box_index];
        cJSON *b = array_object(bins); char id[32];
        if (!b) goto oom;
        snprintf(id, sizeof id, "bin-%d", i + 1);
        ADD_STR(b,"id",id); ADD_STR(b,"type_id",box->id);
        ADD_NUM(b,"width",box->width); ADD_NUM(b,"length",box->length); ADD_NUM(b,"height",box->height);
        ADD_NUM(b,"max_weight",box->max_weight); ADD_NUM(b,"cost",box->cost); ADD_NUM(b,"weight",bin->weight);
        cJSON *items = cJSON_AddArrayToObject(b,"items");
        if (!items) goto oom;
        for (int j = 0; j < result->placement_count; ++j) {
            const OpPlacement *p = &result->placements[j];
            if (p->bin_index != i) continue;
            const OpItem *item = &request->items[p->item_index];
            cJSON *it = array_object(items); if (!it) goto oom;
            ADD_STR(it,"id",item->id); ADD_NUM(it,"instance",item->instance);
            ADD_NUM(it,"x",p->x); ADD_NUM(it,"y",p->y); ADD_NUM(it,"z",p->z);
            ADD_NUM(it,"width",p->width); ADD_NUM(it,"length",p->length); ADD_NUM(it,"height",p->height);
            ADD_NUM(it,"angle",p->angle); ADD_NUM(it,"weight",item->weight);
        }
    }
    for (int i = 0; i < result->unpacked_count; ++i) {
        const OpItem *item = &request->items[result->unpacked[i]];
        cJSON *it = array_object(unpacked); if (!it) goto oom;
        ADD_STR(it,"id",item->id); ADD_NUM(it,"instance",item->instance);
    }
    cJSON *stats = cJSON_AddObjectToObject(root,"stats"); if (!stats) goto oom;
    ADD_NUM(stats,"elapsed_ms",result->elapsed_ms); ADD_NUM(stats,"candidates",result->candidates);
    ADD_NUM(stats,"restarts",result->restarts); ADD_NUM(stats,"box_count",result->bin_count);
    ADD_NUM(stats,"total_cost",result->total_cost); ADD_NUM(stats,"utilization",result->utilization);
    ADD_BOOL(stats,"timed_out",result->timed_out); ADD_BOOL(stats,"budget_exhausted",result->budget_exhausted);
    ADD_NUM(stats,"lower_bound",result->lower_bound); ADD_BOOL(stats,"proven_optimal",result->proven_optimal);
    return root;
oom:
    cJSON_Delete(root); return NULL;
}
static int print_json(cJSON *root) {
    char *json = root ? cJSON_PrintUnformatted(root) : NULL;
    if (!json) { fputs("{\"error\":\"Out of memory\"}\n", stdout); return 0; }
    int ok = fputs(json, stdout) >= 0 && fputc('\n',stdout) != EOF;
    cJSON_free(json); return ok;
}
static int print_error(const char *message) {
    cJSON *error = cJSON_CreateObject();
    if (!error || !cJSON_AddStringToObject(error,"error",message)) {
        cJSON_Delete(error); fputs("{\"error\":\"Out of memory\"}\n", stdout); return 1;
    }
    print_json(error); cJSON_Delete(error); return 1;
}
int main(int argc, char **argv) {
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    if (argc == 2 && !strcmp(argv[1],"--help")) {
        puts("paCker " OP_VERSION "\nUsage: packer [request.json]\nRead one JSON request from stdin or a UTF-8 file (maximum 1 MiB).\nPrint one JSON result to stdout; invalid input returns a nonzero exit code.\nLimits: 256 items, 64 box types, 63 UTF-8 bytes per ID.\nSee docs/design.md for ordinary packing and docs/schema2.md for geometric mode."); return 0;
    }
    if (argc == 2 && !strcmp(argv[1],"--version")) { puts("paCker " OP_VERSION); return 0; }
    if (argc == 2 && !strcmp(argv[1],"--capabilities")) {
        puts("{\"protocol\":1,\"ordinary_version\":\"" OP_VERSION "\","
             "\"geometric_version\":\"" OP3_VERSION "\",\"schemas\":[1,2],"
             "\"support_modes\":[\"contact\",\"full_base\",\"geometric\"],"
             "\"rotations\":[\"none\",\"flat\",\"any\",\"free3d\"],"
             "\"limits\":{\"request_bytes\":1048576,\"json_depth\":16,"
             "\"expanded_items\":256,\"box_types\":64,\"id_utf8_bytes\":63}}");
        return 0;
    }
    if (argc > 2) return print_error("Usage: packer [request.json]");
    FILE *input = stdin;
    if (argc == 2) {
#ifdef _WIN32
        /* main's narrow argv loses characters outside the active code page.
         * Re-read the original UTF-16 command line for filesystem access. */
        int wide_argc = 0;
        wchar_t **wide_argv = CommandLineToArgvW(GetCommandLineW(), &wide_argc);
        input = wide_argv && wide_argc == 2 ? _wfopen(wide_argv[1], L"rb") : NULL;
        if (wide_argv) LocalFree(wide_argv);
#else
        input = fopen(argv[1],"rb");
#endif
    }
    if (!input) return print_error("Cannot open input file");
    char *buffer = malloc(INPUT_LIMIT + 2);
    if (!buffer) { if (input != stdin) fclose(input); return print_error("Out of memory"); }
    size_t length = fread(buffer, 1, INPUT_LIMIT + 1, input);
    int read_error = ferror(input);
    if (input != stdin) fclose(input);
    if (read_error || length > INPUT_LIMIT) {
        free(buffer); return print_error(read_error ? "Cannot read input" : "Input exceeds 1 MiB limit");
    }
    buffer[length] = '\0';
    Scanner scanner = {(const unsigned char *)buffer, (const unsigned char *)buffer + length};
    int valid = json_value(&scanner, 0); whitespace(&scanner);
    if (!valid || scanner.p != scanner.end) { free(buffer); return print_error("Invalid JSON, UTF-8, embedded NUL, or nesting depth"); }
    cJSON *root = cJSON_ParseWithLength(buffer, length + 1); free(buffer);
    if (!root) return print_error("Cannot parse JSON");
    const cJSON *options = member(root, "options");
    const cJSON *mode = member(options, "support_mode");
    if (mode && (!cJSON_IsString(mode) ||
        (strcmp(mode->valuestring, "contact") && strcmp(mode->valuestring, "full_base") &&
         strcmp(mode->valuestring, "geometric")))) {
        cJSON_Delete(root); return print_error("support_mode must be contact, full_base or geometric");
    }
    if (mode && !strcmp(mode->valuestring, "geometric")) {
        Op3Request request; Op3Result result; char error[256] = {0};
        int ok = op3_request_from_json(root, &request, error); cJSON_Delete(root);
        if (!ok) return print_error(error);
        if (op3_pack(&request, &result, error, sizeof error)) return print_error(error[0] ? error : "Packing failed");
        root = op3_result_to_json(&request, &result);
        ok = print_json(root); cJSON_Delete(root);
        return ok ? 0 : 1;
    }
    OpRequest request; OpResult result; char error[256] = {0};
    int ok = request_from_json(root, &request, error); cJSON_Delete(root);
    if (!ok) return print_error(error);
    if (op_pack(&request, &result, error, sizeof error)) return print_error(error[0] ? error : "Packing failed");
    root = result_to_json(&request, &result);
    ok = print_json(root); cJSON_Delete(root);
    return ok ? 0 : 1;
}

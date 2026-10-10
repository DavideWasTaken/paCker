#include "json3d.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

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
    if (!cJSON_IsString(v) || !*v->valuestring || strlen(v->valuestring) >= OP3_ID_SIZE)
        return fail(error, "id must contain 1..63 UTF-8 bytes");
    strcpy(id, v->valuestring); return 1;
}
#define NUM(obj,key,lo,hi,integer,required,def,out) \
    do { if (!number(obj,key,lo,hi,integer,required,def,out,error)) return 0; } while(0)
#define DIM(obj,key,out) NUM(obj,key,0.0001,1000000,0,1,0,out)
int op3_request_from_json(const cJSON *root, Op3Request *request, char *error) {
    static const char *const root_fields[] = {"boxes", "items", "options", NULL};
    static const char *const box_fields[] = {"id", "width", "length", "height", "max_weight", "cost", "quantity", NULL};
    static const char *const item_fields[] = {"id", "width", "length", "height", "weight", "quantity", "rotation", "diagonal", NULL};
    static const char *const option_fields[] = {"angle_step", "restarts", "max_candidates", "time_limit_ms", "seed", "gap", "support_mode", "clearance", NULL};
    if (!fields(root, root_fields, error)) return 0;
    const cJSON *boxes = member(root, "boxes"), *items = member(root, "items"), *options = member(root, "options");
    if (!cJSON_IsArray(boxes) || !cJSON_IsArray(items)) return fail(error, "boxes and items arrays are required");
    if (cJSON_GetArraySize(boxes) > OP3_MAX_BOXES || cJSON_GetArraySize(items) > OP3_MAX_ITEMS)
        return fail(error, "Limit exceeded: 64 box types, 256 expanded items");
    memset(request, 0, sizeof *request);
    op3_default_options(&request->options);
    for (const cJSON *p = boxes->child; p; p = p->next) {
        Op3Box *b = &request->boxes[request->box_count]; double quantity;
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
        Op3Item item = {0}; double quantity;
        if (!fields(p, item_fields, error) || !identity(p, item.id, error)) return 0;
        for (int i = 0; i < request->item_count; ++i)
            if (!strcmp(item.id, request->items[i].id)) return fail(error, "Duplicate item id");
        DIM(p,"width",&item.width); DIM(p,"length",&item.length); DIM(p,"height",&item.height);
        NUM(p,"weight",0,1e12,0,0,0,&item.weight);
        NUM(p,"quantity",1,256,1,0,1,&quantity);
        if (request->item_count + (int)quantity > OP3_MAX_ITEMS) return fail(error, "Limit exceeded: 256 expanded items");
        item.rotation = OP3_FLAT; item.diagonal = 1;
        const cJSON *rotation = member(p,"rotation"), *diagonal = member(p,"diagonal");
        if (rotation) {
            if (!cJSON_IsString(rotation)) return fail(error, "rotation must be none, flat, any, or free3d");
            if (!strcmp(rotation->valuestring,"none")) item.rotation = OP3_NONE;
            else if (!strcmp(rotation->valuestring,"flat")) item.rotation = OP3_FLAT;
            else if (!strcmp(rotation->valuestring,"any")) item.rotation = OP3_ANY;
            else if (!strcmp(rotation->valuestring,"free3d")) item.rotation = OP3_FREE3D;
            else return fail(error, "rotation must be none, flat, any, or free3d");
        }
        if (diagonal) {
            if (!cJSON_IsBool(diagonal)) return fail(error,"diagonal must be boolean");
            item.diagonal = cJSON_IsTrue(diagonal);
        }
        if (item.rotation == OP3_FREE3D && !item.diagonal) return fail(error,"free3d requires diagonal true");
        for (int i = 0; i < (int)quantity; ++i) {
            item.instance = i; request->items[request->item_count++] = item;
        }
    }
    if (options) {
        if (!fields(options, option_fields, error)) return 0;
        Op3Options *o = &request->options; double value;
        NUM(options,"angle_step",1,90,1,0,o->angle_step,&o->angle_step);
        NUM(options,"time_limit_ms",1,60000,0,0,o->time_limit_ms,&o->time_limit_ms);
        double gap;
        NUM(options,"gap",0,1e6,0,0,0,&gap);
        if (gap != 0) return fail(error,"Geometric mode requires gap zero; use clearance");
        NUM(options,"clearance",0,1e6,0,0,o->clearance,&o->clearance);
        const cJSON *mode = member(options,"support_mode");
        if (!cJSON_IsString(mode) || strcmp(mode->valuestring,"geometric")) return fail(error,"Expected geometric support_mode");
        NUM(options,"restarts",1,64,1,0,o->restarts,&value); o->restarts = (int)value;
        NUM(options,"seed",0,4294967295.0,1,0,o->seed,&value); o->seed = (unsigned)value;
        NUM(options,"max_candidates",1,100000000,1,0,(double)o->max_candidates,&value); o->max_candidates = (uint64_t)value;
    }
    return 1;
}

/* cJSON's ordinary number printer deliberately stays unchanged. Raw JSON
 * numeric tokens preserve every binary64 value in this new schema only. */
static int number_token(char token[32], double value) {
    if (!isfinite(value)) return 0;
    if (value == 0 && signbit(value)) strcpy(token,"-0.0");
    else snprintf(token,32,"%.17g",value);
    return 1;
}
static int add_number(cJSON *object, const char *key, double value) {
    char token[32];
    if (!number_token(token,value)) return 0;
    cJSON *number = cJSON_CreateRaw(token);
    if (!number) return 0;
    if (!cJSON_AddItemToObject(object, key, number)) { cJSON_Delete(number); return 0; }
    return 1;
}
static cJSON *add_vector(cJSON *object, const char *key, const double *v, int count) {
    cJSON *array = cJSON_AddArrayToObject(object, key);
    if (!array) return NULL;
    for (int i = 0; i < count; ++i) {
        char token[32];
        if (!number_token(token,v[i])) return NULL;
        cJSON *number = cJSON_CreateRaw(token);
        if (!number) return NULL;
        if (!cJSON_AddItemToArray(array, number)) { cJSON_Delete(number); return NULL; }
    }
    return array;
}
static cJSON *array_object(cJSON *array) {
    cJSON *object = cJSON_CreateObject();
    if (object && !cJSON_AddItemToArray(array, object)) { cJSON_Delete(object); return NULL; }
    return object;
}

/* Validate indices before using them: no malformed C result can be silently
 * truncated, indexed out of bounds, or emitted with missing identities. */
static int result_integrity(const Op3Request *r, const Op3Result *s) {
    if (s->placement_count < 0 || s->placement_count > r->item_count ||
        s->unpacked_count < 0 || s->unpacked_count > r->item_count ||
        s->placement_count + s->unpacked_count != r->item_count ||
        s->bin_count < 0 || s->bin_count > s->placement_count ||
        s->stop_reason < OP3_SEARCH_EXHAUSTED || s->stop_reason > OP3_CANDIDATE_LIMIT ||
        s->timed_out != (s->stop_reason == OP3_TIME_LIMIT) ||
        s->budget_exhausted != (s->stop_reason == OP3_CANDIDATE_LIMIT) ||
        (s->stop_reason <= OP3_COMPLETED && (s->stop_reason == OP3_COMPLETED) != (s->unpacked_count == 0)) ||
        s->candidates > r->options.max_candidates || s->xy_candidates > s->candidates ||
        s->restarts < 0 || s->restarts > r->options.restarts ||
        !isfinite(s->elapsed_ms) || s->elapsed_ms < 0 ||
        !isfinite(s->xy_elapsed_ms) || s->xy_elapsed_ms < 0 || s->xy_elapsed_ms > s->elapsed_ms ||
        !isfinite(s->total_cost) || s->total_cost < 0 || !isfinite(s->utilization) || s->utilization < 0 ||
        (s->timed_out && s->elapsed_ms < r->options.time_limit_ms) ||
        (s->budget_exhausted && s->candidates != r->options.max_candidates)) return 0;
    unsigned char seen[OP3_MAX_ITEMS] = {0}, used[OP3_MAX_ITEMS] = {0};
    for (int i = 0; i < s->bin_count; ++i)
        if (s->bins[i].box_index < 0 || s->bins[i].box_index >= r->box_count ||
            !isfinite(s->bins[i].weight) || s->bins[i].weight < 0) return 0;
    for (int i = 0; i < s->placement_count; ++i) {
        const Op3Placement *p = &s->placements[i];
        if (p->item_index < 0 || p->item_index >= r->item_count || seen[p->item_index]++ ||
            p->bin_index < 0 || p->bin_index >= s->bin_count) return 0;
        const Op3Item *item = &r->items[p->item_index];
        if (p->pose.width != item->width || p->pose.length != item->length || p->pose.height != item->height) return 0;
        used[p->bin_index] = 1;
    }
    for (int i = 0; i < s->unpacked_count; ++i) {
        int index = s->unpacked[i];
        if (index < 0 || index >= r->item_count || seen[index]++) return 0;
    }
    for (int i = 0; i < s->bin_count; ++i) if (!used[i]) return 0;
    return 1;
}
#define ADD_NUM(obj,key,val) do { if (!add_number(obj,key,(double)(val))) goto oom; } while(0)
#define ADD_STR(obj,key,val) do { if (!cJSON_AddStringToObject(obj,key,val)) goto oom; } while(0)
#define ADD_BOOL(obj,key,val) do { if (!cJSON_AddBoolToObject(obj,key,val)) goto oom; } while(0)
cJSON *op3_result_to_json(const Op3Request *request, const Op3Result *result) {
    if (!result_integrity(request, result)) return NULL;
    static const char *const reasons[] = {"search_exhausted", "completed", "time_limit", "candidate_limit"};
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    ADD_STR(root,"version",op3_version()); ADD_NUM(root,"schema_version",2);
    ADD_STR(root,"support_mode","geometric"); ADD_NUM(root,"clearance",request->options.clearance);
    ADD_STR(root,"status",result->unpacked_count ? "partial" : "complete");
    cJSON *bins = cJSON_AddArrayToObject(root,"bins"), *unpacked = cJSON_AddArrayToObject(root,"unpacked");
    if (!bins || !unpacked) goto oom;
    for (int i = 0; i < result->bin_count; ++i) {
        const Op3Bin *bin = &result->bins[i]; const Op3Box *box = &request->boxes[bin->box_index];
        cJSON *b = array_object(bins); char id[32];
        if (!b) goto oom;
        snprintf(id, sizeof id, "bin-%d", i + 1);
        ADD_STR(b,"id",id); ADD_STR(b,"type_id",box->id);
        ADD_NUM(b,"width",box->width); ADD_NUM(b,"length",box->length); ADD_NUM(b,"height",box->height);
        ADD_NUM(b,"max_weight",box->max_weight); ADD_NUM(b,"cost",box->cost); ADD_NUM(b,"weight",bin->weight);
        cJSON *items = cJSON_AddArrayToObject(b,"items");
        if (!items) goto oom;
        for (int j = 0; j < result->placement_count; ++j) {
            const Op3Placement *p = &result->placements[j];
            if (p->bin_index != i) continue;
            const Op3Item *item = &request->items[p->item_index];
            cJSON *it = array_object(items); if (!it) goto oom;
            ADD_STR(it,"id",item->id); ADD_NUM(it,"instance",item->instance);
            ADD_NUM(it,"width",p->pose.width); ADD_NUM(it,"length",p->pose.length); ADD_NUM(it,"height",p->pose.height);
            ADD_NUM(it,"weight",item->weight);
            if (!add_vector(it,"center",p->pose.center,3) || !add_vector(it,"orientation",p->pose.orientation,4)) goto oom;
        }
    }
    for (int i = 0; i < result->unpacked_count; ++i) {
        const Op3Item *item = &request->items[result->unpacked[i]];
        cJSON *it = array_object(unpacked); if (!it) goto oom;
        ADD_STR(it,"id",item->id); ADD_NUM(it,"instance",item->instance);
    }
    cJSON *stats = cJSON_AddObjectToObject(root,"stats"); if (!stats) goto oom;
    ADD_NUM(stats,"elapsed_ms",result->elapsed_ms); ADD_NUM(stats,"candidates",result->candidates);
    ADD_NUM(stats,"restarts",result->restarts); ADD_NUM(stats,"box_count",result->bin_count);
    ADD_NUM(stats,"total_cost",result->total_cost); ADD_NUM(stats,"utilization",result->utilization);
    ADD_BOOL(stats,"timed_out",result->timed_out); ADD_BOOL(stats,"budget_exhausted",result->budget_exhausted);
    ADD_STR(stats,"stop_reason",reasons[result->stop_reason]); ADD_NUM(stats,"seed",request->options.seed);
    ADD_NUM(stats,"xy_candidates",result->xy_candidates); ADD_NUM(stats,"xy_elapsed_ms",result->xy_elapsed_ms);
    cJSON *options = cJSON_AddObjectToObject(stats,"options"); if (!options) goto oom;
    ADD_STR(options,"support_mode","geometric"); ADD_NUM(options,"clearance",request->options.clearance);
    ADD_NUM(options,"gap",0); ADD_NUM(options,"seed",request->options.seed);
    ADD_NUM(options,"angle_step",request->options.angle_step); ADD_NUM(options,"time_limit_ms",request->options.time_limit_ms);
    ADD_NUM(options,"restarts",request->options.restarts); ADD_NUM(options,"max_candidates",request->options.max_candidates);
    return root;
oom:
    cJSON_Delete(root); return NULL;
}

#include "../src/json3d.h"
#undef NDEBUG
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static void round_trip(const Op3Request *request, const Op3Result *result) {
    cJSON *tree = op3_result_to_json(request,result);
    assert(tree);
    char *text = cJSON_PrintUnformatted(tree);
    assert(text);
    /* PHP/Python decode bare -0 as integer zero. Keep signed binary64 zero. */
    if (signbit(result->placements[0].pose.orientation[0]) && result->placements[0].pose.orientation[0]==0)
        assert(strstr(text,"-0.0"));
    cJSON *decoded = cJSON_Parse(text);
    assert(decoded);
    cJSON *bins = cJSON_GetObjectItemCaseSensitive(decoded,"bins");
    for (int i=0;i<result->placement_count;++i) {
        const Op3Placement *placement=&result->placements[i];
        cJSON *bin=cJSON_GetArrayItem(bins,placement->bin_index);
        cJSON *items=cJSON_GetObjectItemCaseSensitive(bin,"items");
        cJSON *item=NULL;
        for (cJSON *it=items->child;it;it=it->next) {
            cJSON *id=cJSON_GetObjectItemCaseSensitive(it,"id");
            cJSON *instance=cJSON_GetObjectItemCaseSensitive(it,"instance");
            if (!strcmp(id->valuestring,request->items[placement->item_index].id) &&
                instance->valuedouble==request->items[placement->item_index].instance) { item=it;break; }
        }
        assert(item);
        for (int j=0;j<3;++j) {
            double value=cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(item,"center"),j)->valuedouble;
            assert(memcmp(&value,&placement->pose.center[j],sizeof value)==0);
        }
        for (int j=0;j<4;++j) {
            double value=cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(item,"orientation"),j)->valuedouble;
            assert(memcmp(&value,&placement->pose.orientation[j],sizeof value)==0);
        }
        const char *dimensions[]={"width","length","height"};
        const double original[]={placement->pose.width,placement->pose.length,placement->pose.height};
        for (int j=0;j<3;++j) assert(cJSON_GetObjectItemCaseSensitive(item,dimensions[j])->valuedouble==original[j]);
    }
    cJSON_Delete(decoded);cJSON_free(text);cJSON_Delete(tree);
}
int main(void) {
    Op3Request request={0};Op3Result result;char error[256];
    op3_default_options(&request.options);
    request.options.max_candidates=4000;request.options.time_limit_ms=10000;request.options.restarts=1;
    request.box_count=request.item_count=1;
    request.boxes[0]=(Op3Box){"box",100,100,100,1e12,1,1};
    request.items[0]=(Op3Item){"rod",150,8,8,0,0,OP3_FREE3D,1};
    assert(!op3_pack(&request,&result,error,sizeof error));
    assert(!result.unpacked_count);
    round_trip(&request,&result);
    request.items[0]=(Op3Item){"decimal",0.12345678901234566,0.23456789012345678,0.3456789012345679,0,0,OP3_NONE,1};
    assert(!op3_pack(&request,&result,error,sizeof error));
    round_trip(&request,&result);
    result.placements[0].pose.orientation[0]=-0.0;
    round_trip(&request,&result);
    for (int i=0;i<2;++i) {
        double side=i?1000000:0.0001;
        request.items[0].width=request.items[0].length=request.items[0].height=side;
        request.boxes[0].width=request.boxes[0].length=request.boxes[0].height=side;
        assert(!op3_pack(&request,&result,error,sizeof error));
        assert(!result.unpacked_count);
        round_trip(&request,&result);
    }
    Op3Result bad=result;
    bad.placements[0].item_index=-1;assert(!op3_result_to_json(&request,&bad));
    bad=result;bad.bins[0].box_index=64;assert(!op3_result_to_json(&request,&bad));
    bad=result;bad.placement_count=257;assert(!op3_result_to_json(&request,&bad));
    bad=result;bad.placements[0].pose.center[0]=INFINITY;assert(!op3_result_to_json(&request,&bad));
    bad=result;bad.xy_candidates=bad.candidates+1;assert(!op3_result_to_json(&request,&bad));
    bad=result;bad.stop_reason=77;assert(!op3_result_to_json(&request,&bad));
    puts("schema2: exact double round trips and malformed C results passed");
    return 0;
}

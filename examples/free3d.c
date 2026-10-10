/* Direct in-process C API: no PHP, JSON parsing, CLI or service required.
   CMake builds free3d_example against the static packer3d library. */
#include "packer3d.h"
#include <stdio.h>
int main(void) {
    Op3Request request={0};Op3Result result;char error[128];
    op3_default_options(&request.options);
    request.item_count=request.box_count=1;
    request.items[0]=(Op3Item){"rod",150,8,8,0,0,OP3_FREE3D,1};
    request.boxes[0]=(Op3Box){"cube",100,100,100,1e12,1,-1};
    if(op3_pack(&request,&result,error,sizeof error)){fprintf(stderr,"%s\n",error);return 1;}
    printf("packed=%d unpacked=%d bins=%d candidates=%llu elapsed_ms=%.3f\n",result.placement_count,result.unpacked_count,result.bin_count,(unsigned long long)result.candidates,result.elapsed_ms);
    for(int i=0;i<result.placement_count;i++) {
        const Op3Pose *p=&result.placements[i].pose;
        printf("center=[%.17g,%.17g,%.17g] quaternion=[%.17g,%.17g,%.17g,%.17g]\n",p->center[0],p->center[1],p->center[2],p->orientation[0],p->orientation[1],p->orientation[2],p->orientation[3]);
    }
    return result.unpacked_count?2:0;
}

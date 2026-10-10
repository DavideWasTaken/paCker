#include "packer3d.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
int main(void) {
    Op3Request r={0};Op3Result out;char error[128];
    op3_default_options(&r.options);
    assert(r.options.angle_step==15&&r.options.restarts==8&&r.options.max_candidates==200000);
    assert(op3_pack(&r,&out,error,sizeof error)==0&&out.unpacked_count==0);
    r.item_count=1;r.box_count=1;
    r.items[0]=(Op3Item){"rod",150,8,8,1,0,OP3_FREE3D,1};
    r.boxes[0]=(Op3Box){"cube",100,100,100,10,1,1};
    assert(op3_pack(&r,&out,error,sizeof error)==0);
    assert(out.placement_count==1&&out.bin_count==1&&out.unpacked_count==0);
    int inside=0;double sides[3]={100,100,100};
    assert(op3_inside(&out.placements[0].pose,sides,0,&inside)==0&&inside);
    r.items[0].rotation=OP3_ANY;
    assert(op3_pack(&r,&out,error,sizeof error)==0&&out.unpacked_count==1);
    r.items[0].weight=NAN;
    assert(op3_pack(&r,&out,error,sizeof error)==1&&out.candidates==0&&out.placement_count==0&&error[0]);
    puts("free3d C API tests passed");return 0;
}

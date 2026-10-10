/* Direct ordinary C API. Expand quantities into identified instances. */
#include "oblique.h"
#include <stdio.h>
int main(void) {
    OpRequest request={0};OpResult result;char error[128];
    op_default_options(&request.options);
    request.item_count=2;request.box_count=1;
    request.items[0]=(OpItem){"product",60,40,20,100,0,OP_FLAT,0};
    request.items[1]=(OpItem){"product",60,40,20,100,1,OP_FLAT,0};
    request.boxes[0]=(OpBox){"box",100,80,40,1000,1,1};
    if(op_pack(&request,&result,error,sizeof error)){fprintf(stderr,"%s\n",error);return 1;}
    printf("packed=%d unpacked=%d bins=%d\n",result.placement_count,result.unpacked_count,result.bin_count);
    for(int i=0;i<result.placement_count;i++) {
        const OpPlacement *p=&result.placements[i];
        printf("item=%d box=%d center_xy=[%.17g,%.17g] bottom_z=%.17g angle_deg=%.17g\n",p->item_index,p->bin_index,p->x,p->y,p->z,p->angle);
    }
    return result.unpacked_count?2:0;
}

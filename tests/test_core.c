#include "oblique.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static OpRequest r;
static OpResult out;
static void reset(void) {
    memset(&r,0,sizeof r); op_default_options(&r.options);
    r.options.max_candidates=100000; r.options.time_limit_ms=5000; r.options.restarts=4;
    r.box_count=1; r.boxes[0]=(OpBox){"box",180,180,30,1000,1,-1};
    r.item_count=1; r.items[0]=(OpItem){"bar",220,30,20,100,0,OP_FLAT,1};
}
static void pack(void) { char err[256]; int rc=op_pack(&r,&out,err,sizeof err); if(rc)puts(err); assert(rc==0); }
int main(void) {
    OpPlacement a={0,0,50,50,0,80,20,10,45};
    OpPlacement b=a; b.x+=5; assert(op_intersects(&a,&b,0));
    b.x=150; assert(!op_intersects(&a,&b,0));
    a=(OpPlacement){0,0,20,20,0,40,40,10,0}; b=a;b.x=60;
    assert(!op_intersects(&a,&b,0)); assert(op_intersects(&a,&b,1));
    b=a;b.z=10;assert(!op_intersects(&a,&b,0));assert(op_supported(&b,&a,1));
    b.x=45;assert(!op_supported(&b,&a,1));
    /* Full coverage may come from adjacent coplanar top faces, but a gap
       or a different top height must never count as support. */
    OpPlacement bases[2]={{0,0,20,20,0,40,40,10,0},{1,0,60,20,0,40,40,10,0}};
    OpPlacement bridge={2,0,40,20,10,80,40,10,0};
    assert(op_supported(&bridge,bases,2));
    /* A tiny area fraction is not permission to bridge a real gap. */
    OpPlacement long_bases[2]={{0,0,249999.99925,.5,0,499999.9985,1,10,0},
                               {1,0,749999.99875,.5,0,499999.9985,1,10,0}};
    OpPlacement long_bridge={2,0,499999.999,.5,10,999999.998,1,1,0};
    assert(!op_supported(&long_bridge,long_bases,2));
    /* Small missing corner: area alone can also hide a triangular void. */
    OpPlacement corner_base={0,0,0,0,0,100,100,10,45};
    OpPlacement corner_bridge={1,0,0,0,10,70.710679,70.710679,1,0};
    assert(!op_supported(&corner_bridge,&corner_base,1));
    bases[1].x=61;assert(!op_supported(&bridge,bases,2));
    bases[1].x=60;bases[1].height=9;assert(!op_supported(&bridge,bases,2));
    /* The same union after a 45-degree rigid rotation. */
    bases[0]=(OpPlacement){0,0,-14.142135623730951,-14.142135623730951,0,40,40,10,45};
    bases[1]=(OpPlacement){1,0,14.142135623730951,14.142135623730951,0,40,40,10,45};
    bridge=(OpPlacement){2,0,0,0,10,80,40,10,45};
    assert(op_supported(&bridge,bases,2));
    reset();pack();assert(out.unpacked_count==0 && out.bin_count==1);
    assert(op_inside(&out.placements[0],&r.boxes[0],0));
    assert(fabs(out.placements[0].angle-45)<0.01);
    r.items[0].diagonal=0;pack();assert(out.unpacked_count==1 && out.bin_count==0);
    reset();r.items[0].rotation=OP_NONE;pack();assert(out.unpacked_count==1);
    reset();r.boxes[0]=(OpBox){"cube",40,40,40,100,1,1};
    r.items[0]=(OpItem){"cube",40,40,20,60,0,OP_FLAT,0};
    r.items[1]=r.items[0];r.items[1].instance=1;r.item_count=2;
    pack();assert(out.placement_count==1 && out.unpacked_count==1);
    r.boxes[0].max_weight=120;pack();assert(out.placement_count==2 && out.bin_count==1);
    r.boxes[0].quantity=0;pack();assert(out.placement_count==0);
    reset();r.items[0]=(OpItem){"upright",20,20,60,1,0,OP_FLAT,0};pack();assert(out.unpacked_count==1);
    r.items[0].rotation=OP_ANY;pack();assert(out.unpacked_count==0);
    /* Swapping a supporting face adds distinct sampled yaws when the angle
       step does not divide 90 degrees (the fitting yaw here is 43 degrees). */
    reset();r.boxes[0]=(OpBox){"sampled-yaw",17,16,1,100,1,1};
    r.items[0]=(OpItem){"bar",22,1,1,1,0,OP_ANY,1};
    r.options.angle_step=7;r.options.restarts=1;
    pack();assert(out.unpacked_count==0 && out.bin_count==1);
    reset();r.item_count=0;pack();assert(out.bin_count==0 && out.unpacked_count==0);
    reset();r.options.max_candidates=1;pack();assert(out.candidates<=1 && out.budget_exhausted);
    reset();r.items[0].width=-1;char err[256];assert(op_pack(&r,&out,err,sizeof err)!=0);
    reset();r.items[0].width=NAN;assert(op_pack(&r,&out,err,sizeof err)!=0);
    reset();r.box_count=2;
    r.boxes[0]=(OpBox){"cheap",1,1,1,100,1,1};r.boxes[1]=(OpBox){"large",2,1,1,100,10,1};
    r.items[0]=(OpItem){"unit",1,1,1,1,0,OP_NONE,0};r.items[1]=r.items[0];r.items[1].instance=1;r.item_count=2;
    r.options.restarts=1;r.options.max_candidates=5;pack();assert(out.unpacked_count==0&&out.total_cost==10);
    r.options.max_candidates=100;pack();assert(out.unpacked_count==0&&out.total_cost==10);
    reset();r.boxes[0].max_weight=0;r.items[0].weight=5e-8;pack();assert(out.unpacked_count==1);
    reset();r.boxes[0]=(OpBox){"fractional",3,1,1,0.3,1,1};r.item_count=3;
    for(int k=0;k<3;k++)r.items[k]=(OpItem){"unit",1,1,1,0.1,k,OP_NONE,0};
    pack();assert(out.unpacked_count==0);
    reset();r.boxes[0]=(OpBox){"tiny",0.0001,0.0001,0.0001,1,1,1};
    r.items[0]=(OpItem){"tiny",0.00010005,0.00010005,0.00010005,0,0,OP_NONE,0};
    pack();assert(out.unpacked_count==1);
    r.items[0].width=r.items[0].length=r.items[0].height=0.0001;
    pack();assert(out.unpacked_count==0 && out.utilization<=1+1e-7);
    /* An orientation chosen before its position strands the second rectangle.
       Both 2x3 rectangles tile the 3x4 floor when rotated together. */
    reset();r.boxes[0]=(OpBox){"tile",3,4,1,100,1,1};r.item_count=2;
    for(int k=0;k<2;k++)r.items[k]=(OpItem){"tile",2,3,1,1,k,OP_FLAT,0};
    r.options.restarts=1;pack();assert(out.unpacked_count==0 && out.bin_count==1);
    reset();r.boxes[0]=(OpBox){"grid",50,40,10,100,1,1};r.item_count=20;
    for(int k=0;k<20;k++)r.items[k]=(OpItem){"cube",10,10,10,1,k,OP_NONE,0};
    r.options.restarts=1;r.options.max_candidates=100;
    pack();assert(out.unpacked_count==0 && out.candidates<=100);
    reset();r.box_count=2;r.boxes[0]=(OpBox){"small",2,1,1,100,1,2};
    r.boxes[1]=(OpBox){"large",3,1,1,100,1,1};r.item_count=4;
    for(int k=0;k<4;k++)r.items[k]=(OpItem){"unit",1,1,1,1,k,OP_NONE,0};
    pack();assert(out.unpacked_count==0 && out.bin_count==2);
    assert(out.bins[0].box_index==0 && out.bins[1].box_index==0);
    /* Count per cost and count density both strand a costly remainder here.
       Keeping an alternative first box permits the cheaper pair of fives. */
    reset();r.box_count=3;r.item_count=10;
    r.boxes[0]=(OpBox){"three",3,1,1,100,0.6,-1};
    r.boxes[1]=(OpBox){"five",5,1,1,100,1,2};
    r.boxes[2]=(OpBox){"six",6,1,1,100,1.1,1};
    for(int k=0;k<10;k++)r.items[k]=(OpItem){"unit",1,1,1,1,k,OP_NONE,0};
    pack();assert(out.unpacked_count==0 && out.bin_count==2 && out.total_cost==2);
    assert(out.bins[0].box_index==1 && out.bins[1].box_index==1);
    reset();r.boxes[0]=(OpBox){"diagonal-strip",100,100,1,100,1,1};r.item_count=4;
    for(int k=0;k<4;k++)r.items[k]=(OpItem){"bar",120,5,1,1,k,OP_FLAT,1};
    pack();assert(out.unpacked_count==0 && out.bin_count==1);
    /* A restart preferring X before Y must also traverse candidate points in
       that order; changing only orientation scoring still strands an item. */
    reset();r.boxes[0]=(OpBox){"floor",10,10,1,100,1,1};r.item_count=5;
    const double traversal_dims[5][2]={{5,2},{6,1},{6,3},{5,5},{5,5}};
    for(int k=0;k<5;k++)r.items[k]=(OpItem){"rectangle",traversal_dims[k][0],traversal_dims[k][1],1,1,k,OP_FLAT,0};
    r.options.restarts=2;pack();assert(out.unpacked_count==0);
    /* A geometric ordering can avoid a second box without extra restarts. */
    reset();r.boxes[0]=(OpBox){"compact",16,12,10,10000,1,-1};r.item_count=8;
    const double portfolio_dims[8][3]={{12,3,4},{2,6,4},{11,4,4},{10,7,5},{10,7,5},{3,7,1},{3,7,1},{3,7,1}};
    for(int k=0;k<8;k++)r.items[k]=(OpItem){"piece",portfolio_dims[k][0],portfolio_dims[k][1],portfolio_dims[k][2],0,k,k==0||k>=5?OP_NONE:OP_FLAT,0};
    r.options.restarts=5;pack();assert(out.unpacked_count==0&&out.bin_count==1);
    /* Exact right-angle rotations must not inflate very thin footprints via
       cos(90deg) residue. Test both face dedup and the interval sweep. */
    reset();r.boxes[0]=(OpBox){"thin",0.0001,1000000,1,100,1,1};
    r.items[0]=(OpItem){"thin",1000000,0.0001,1,1,0,OP_ANY,0};
    r.options.restarts=1;pack();assert(out.unpacked_count==0);
    r.boxes[0].width=0.00020000009;r.item_count=2;r.items[0].rotation=OP_FLAT;
    r.items[1]=r.items[0];r.items[1].instance=1;
    pack();assert(out.unpacked_count==0 && out.bin_count==1);
    /* Contact support: any positive overlap with a lower top face, never an
       edge or vertex touch, never floating. Full base stays opt-in. */
    {
        OpPlacement base={0,0,10,10,0,20,20,10,0},top=base;top.z=10;top.x=25;
        assert(op_rests(&top,&base,1)&&!op_supported(&top,&base,1));
        top.x=30;assert(!op_rests(&top,&base,1));
        top.x=31;assert(!op_rests(&top,&base,1));
        top.x=10;top.z=11;assert(!op_rests(&top,&base,1));
        top=base;top.z=10;top.angle=45;top.x=32;assert(op_rests(&top,&base,1));
        OpPlacement floor_item=base;assert(op_rests(&floor_item,NULL,0));
    }
    reset();assert(r.options.support==OP_SUPPORT_CONTACT&&!r.options.improve);
    r.options.support=2;assert(op_pack(&r,&out,NULL,0)==1);
    /* Lower bound and improvement: four half-box cubes need two boxes. */
    reset();r.boxes[0]=(OpBox){"cube",10,10,10,1000,1,-1};r.item_count=4;
    for(int k=0;k<4;k++)r.items[k]=(OpItem){"half",10,10,6,1,k,OP_NONE,0};
    r.options.improve=1;r.options.time_limit_ms=5000;pack();
    assert(out.bin_count==4&&out.lower_bound==4&&out.proven_optimal&&out.elapsed_ms<5000);
    reset();r.options.improve=2;assert(op_pack(&r,&out,NULL,0)==1);
    puts("core: geometry, diagonal, rotation, support, contact, bounds, improve, stock, weight, empty, budgets, incumbent, orientation selection and invalid inputs passed");
    return 0;
}

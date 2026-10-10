/* Internal algorithm check: start from a certified non-grid pose in open
   space, then require both quaternion and position refinement to improve it.
   End-to-end tests independently verify emitted poses with Decimal60. */
#include "../src/search3d.c"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <stdio.h>
int main(void) {
    Op3Request r={0};Op3Result result={0};
    r.options=(Op3Options){15,60000,0,10000,42,2};r.item_count=r.box_count=1;
    r.items[0]=(Op3Item){"rod",150,8,8,0,0,OP3_FREE3D,1};
    r.boxes[0]=(Op3Box){"cube",100,100,100,100,1,-1};
    Search s={0};s.r=&r;s.best=&result;s.start=op3_search_now_ms();s.deadline=s.phase_deadline=s.start+60000;s.phase_limit=10000;s.tilted=1;
    Layout *layout=calloc(1,sizeof *layout);assert(layout);
    Op3Pose pose={150,8,8,{50,50,50},{0}};double direction[3]={1,1,1};
    direction_quaternion(direction,0,.193,pose.orientation);
    Pick picks[PICKS]={0};assert(validate_pose(&s,layout,0,&r.boxes[0],&pose,&picks[0]));
    picks[0].rank=pose_rank(&picks[0],&r.boxes[0]);double before=picks[0].rank;
    refine_placement(&s,layout,0,&r.items[0],&r.boxes[0],picks);
    assert(picks[0].rank<before);
    double angle=0,position=0;
    for(int k=0;k<4;k++)angle+=fabs(picks[0].pose.orientation[k]-pose.orientation[k]);
    for(int k=0;k<3;k++)position+=fabs(picks[0].pose.center[k]-pose.center[k]);
    assert(angle>1e-6&&position>1e-6);
    Pick checked={0};assert(validate_pose(&s,layout,0,&r.boxes[0],&picks[0].pose,&checked));
    free(layout);puts("coupled quaternion and position refinement passed");return 0;
}

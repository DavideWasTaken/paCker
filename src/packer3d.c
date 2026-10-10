#include "packer3d.h"
#include "search3d.h"
#include "oblique.h"
#include <stdlib.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

const char *op3_version(void) { return OP3_VERSION; }

void op3_default_options(Op3Options *o) {
    if(o)*o=(Op3Options){15,1000,0,200000,42,8};
}
static int fail(char *error,int size,const char *message) {
    if(error&&size>0)snprintf(error,(size_t)size,"%s",message);
    return 1;
}
static int range(double x,double lo,double hi) { return isfinite(x)&&x>=lo&&x<=hi; }
static const char *valid(const Op3Request *r) {
    if(!r)return "null request";
    if(r->item_count<0||r->item_count>OP3_MAX_ITEMS||r->box_count<0||r->box_count>OP3_MAX_BOXES)return "item or box limit exceeded";
    const Op3Options *o=&r->options;
    if(!range(o->angle_step,1,90)||floor(o->angle_step)!=o->angle_step||!range(o->time_limit_ms,1,60000)||!range(o->clearance,0,1e6)||o->max_candidates<1||o->max_candidates>100000000||o->restarts<1||o->restarts>64)return "invalid search options";
    for(int i=0;i<r->item_count;i++) {
        const Op3Item *a=&r->items[i];
        if(!memchr(a->id,0,OP3_ID_SIZE)||!a->id[0]||!range(a->width,1e-4,1e6)||!range(a->length,1e-4,1e6)||!range(a->height,1e-4,1e6)||!range(a->weight,0,1e12)||a->instance<0||a->instance>=OP3_MAX_ITEMS||a->rotation<OP3_NONE||a->rotation>OP3_FREE3D||a->diagonal<0||a->diagonal>1)return "invalid item";
        if(a->rotation==OP3_FREE3D&&!a->diagonal)return "free3d requires diagonal permission";
        for(int j=0;j<i;j++)if(!strcmp(a->id,r->items[j].id)&&a->instance==r->items[j].instance)return "duplicate item instance";
    }
    for(int i=0;i<r->box_count;i++) {
        const Op3Box *a=&r->boxes[i];
        if(!memchr(a->id,0,OP3_ID_SIZE)||!a->id[0]||!range(a->width,1e-4,1e6)||!range(a->length,1e-4,1e6)||!range(a->height,1e-4,1e6)||!range(a->max_weight,0,1e12)||!range(a->cost,0,1e12)||a->quantity< -1||a->quantity>OP3_MAX_ITEMS)return "invalid box";
        for(int j=0;j<i;j++)if(!strcmp(a->id,r->boxes[j].id))return "duplicate box id";
    }
    return NULL;
}
/* Active rotation matrix (columns are local axes) to canonical [x,y,z,w]. */
static void quaternion(const double m[3][3],double q[4]) {
    double t=m[0][0]+m[1][1]+m[2][2];
    if(t>0){double k=sqrt(t+1)*2;q[3]=k/4;q[0]=(m[2][1]-m[1][2])/k;q[1]=(m[0][2]-m[2][0])/k;q[2]=(m[1][0]-m[0][1])/k;}
    else if(m[0][0]>m[1][1]&&m[0][0]>m[2][2]){double k=sqrt(1+m[0][0]-m[1][1]-m[2][2])*2;q[3]=(m[2][1]-m[1][2])/k;q[0]=k/4;q[1]=(m[0][1]+m[1][0])/k;q[2]=(m[0][2]+m[2][0])/k;}
    else if(m[1][1]>m[2][2]){double k=sqrt(1+m[1][1]-m[0][0]-m[2][2])*2;q[3]=(m[0][2]-m[2][0])/k;q[0]=(m[0][1]+m[1][0])/k;q[1]=k/4;q[2]=(m[1][2]+m[2][1])/k;}
    else{double k=sqrt(1+m[2][2]-m[0][0]-m[1][1])*2;q[3]=(m[1][0]-m[0][1])/k;q[0]=(m[0][2]+m[2][0])/k;q[1]=(m[1][2]+m[2][1])/k;q[2]=k/4;}
}
/* Ordinary placement (oriented sides, yaw, bottom Z) to a schema 2 pose. */
static int pose_from_ordinary(const Op3Item *a,const OpPlacement *p,Op3Pose *pose) {
    const double d[3]={a->width,a->length,a->height},placed[3]={p->width,p->length,p->height};
    static const int perms[6][3]={{0,1,2},{1,0,2},{0,2,1},{2,0,1},{1,2,0},{2,1,0}};
    static const int parity[6]={1,-1,-1,1,1,-1};
    for(int k=0;k<6;k++) {
        const int *s=perms[k];
        if(d[s[0]]!=placed[0]||d[s[1]]!=placed[1]||d[s[2]]!=placed[2])continue;
        double m[3][3]={{0}},yaw[3][3],r[3][3]={{0}};
        m[0][s[0]]=1;m[1][s[1]]=1;m[2][s[2]]=parity[k];
        double t=p->angle*3.14159265358979323846/180,c=cos(t),n=sin(t);
        if(p->angle==0){c=1;n=0;}else if(p->angle==90){c=0;n=1;}else if(p->angle==180){c=-1;n=0;}else if(p->angle==270){c=0;n=-1;}
        double z[3][3]={{c,-n,0},{n,c,0},{0,0,1}};memcpy(yaw,z,sizeof yaw);
        for(int i=0;i<3;i++)for(int j=0;j<3;j++)for(int h=0;h<3;h++)r[i][j]+=yaw[i][h]*m[h][j];
        Op3Pose raw={a->width,a->length,a->height,{p->x,p->y,p->z+p->height/2},{0}};
        quaternion(r,raw.orientation);
        return op3_pose_canonicalize(&raw,pose)==OP3_OK;
    }
    return 0;
}
/* Orthogonal orders without clearance: the ordinary engine (contact support,
   so stricter than needed) seeds the incumbent. Every converted pose is
   rechecked with the geometric predicates; any doubt discards the seed. */
/* Returns 1 when the seed is proven optimal in count and cost. */
static int seed_from_ordinary(const Op3Request *r,Op3Result *out,double budget_ms) {
    if(r->options.clearance!=0||!r->item_count)return 0;
    for(int i=0;i<r->item_count;i++)if(r->items[i].rotation==OP3_FREE3D)return 0;
    OpRequest *q=calloc(1,sizeof *q);OpResult *o=calloc(1,sizeof *o);int proven=0;
    if(!q||!o){free(q);free(o);return 0;}
    q->item_count=r->item_count;q->box_count=r->box_count;
    for(int i=0;i<r->item_count;i++) {
        const Op3Item *a=&r->items[i];OpItem *b=&q->items[i];
        memcpy(b->id,a->id,OP_ID_SIZE);b->width=a->width;b->length=a->length;b->height=a->height;
        b->weight=a->weight;b->instance=a->instance;b->rotation=a->rotation;b->diagonal=a->diagonal;
    }
    for(int i=0;i<r->box_count;i++) {
        const Op3Box *a=&r->boxes[i];OpBox *b=&q->boxes[i];
        memcpy(b->id,a->id,OP_ID_SIZE);b->width=a->width;b->length=a->length;b->height=a->height;
        b->max_weight=a->max_weight;b->cost=a->cost;b->quantity=a->quantity;
    }
    op_default_options(&q->options);
    q->options.angle_step=r->options.angle_step;q->options.seed=r->options.seed;q->options.restarts=r->options.restarts;
    q->options.max_candidates=r->options.max_candidates;q->options.time_limit_ms=fmax(1,budget_ms);
    q->options.support=OP_SUPPORT_CONTACT;q->options.improve=1;
    if(!op_pack(q,o,NULL,0)) {
        Op3Result *seed=calloc(1,sizeof *seed);int ok=seed!=NULL;
        for(int i=0;ok&&i<o->placement_count;i++) {
            const OpPlacement *p=&o->placements[i];
            Op3Placement *t=&seed->placements[seed->placement_count++];
            t->item_index=p->item_index;t->bin_index=p->bin_index;
            ok=pose_from_ordinary(&r->items[p->item_index],p,&t->pose);
            const Op3Box *box=&r->boxes[o->bins[p->bin_index].box_index];
            double dims[3]={box->width,box->length,box->height};int inside=0;
            ok=ok&&op3_inside(&t->pose,dims,0,&inside)==OP3_OK&&inside;
            for(int j=0;ok&&j<i;j++)if(seed->placements[j].bin_index==t->bin_index) {
                int hit=1;ok=op3_intersects(&t->pose,&seed->placements[j].pose,0,&hit)==OP3_OK&&!hit;
            }
        }
        if(ok) {
            for(int b=0;b<o->bin_count;b++)seed->bins[b]=(Op3Bin){o->bins[b].box_index,o->bins[b].weight};
            seed->bin_count=o->bin_count;
            for(int u=0;u<o->unpacked_count;u++)seed->unpacked[u]=o->unpacked[u];
            seed->unpacked_count=o->unpacked_count;seed->total_cost=o->total_cost;seed->utilization=o->utilization;
            *out=*seed;out->candidates=o->candidates;out->restarts=o->restarts;proven=o->proven_optimal;
        }
        free(seed);
    }
    free(q);free(o);return proven;
}
int op3_pack(const Op3Request *r,Op3Result *out,char *error,int size) {
    double start=op3_search_now_ms();
    if(!out)return fail(error,size,"null result");
    memset(out,0,sizeof *out);
    const char *message=valid(r);
    if(message)return fail(error,size,message);
    /* Half of the budget for the seed; the geometric search keeps the rest and
       can only replace the seed with a strictly better layout. */
    if(seed_from_ordinary(r,out,r->options.time_limit_ms/2)) {
        out->elapsed_ms=op3_search_now_ms()-start;out->stop_reason=OP3_COMPLETED;
        if(error&&size>0)error[0]=0;
        return 0;
    }
    if(op3_search(r,out,start)) {
        memset(out,0,sizeof *out);return fail(error,size,"out of memory");
    }
    if(error&&size>0)error[0]=0;
    return 0;
}

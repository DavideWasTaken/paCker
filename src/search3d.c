#if !defined(_WIN32) && !defined(_POSIX_C_SOURCE)
#define _POSIX_C_SOURCE 200809L
#endif
#include "search3d.h"
#include "geometry3d.h"
#include <float.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <time.h>
#endif

#define PI 3.14159265358979323846264338327950288
#define BEAM 3
#define ORIENTATIONS 48
#define CENTERS 160
#define OP3_PLANES 42
#define PICKS 2
typedef struct { double q[4],m[3][3],extent[3],key[12],rank; } Orientation;
typedef struct { double n[3],d; } Plane;
typedef struct { double v[3],rank; } Center;
typedef struct {
    Op3Result result;
    Op3Obb obbs[OP3_MAX_ITEMS];
    unsigned char used[OP3_MAX_ITEMS];
    int stock[OP3_MAX_BOXES];
    double compact;
} Layout;
typedef struct {
    const Op3Request *r;
    Op3Result *best;
    double start,deadline,phase_deadline;
    uint64_t count,phase_limit;
    uint64_t xy_count;
    double xy_ms;
    unsigned rng;
    int tilted,run,time_stop,candidate_stop,phase_stop,runs;
    int orders[64][OP3_MAX_ITEMS];
} Search;
typedef struct { Op3Pose pose;Op3Obb obb;double rank;int valid; } Pick;

double op3_search_now_ms(void) {
#ifdef _WIN32
    LARGE_INTEGER count,frequency;
    QueryPerformanceCounter(&count);QueryPerformanceFrequency(&frequency);
    return (double)count.QuadPart*1000.0/(double)frequency.QuadPart;
#else
    struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);
    return (double)ts.tv_sec*1000.0+(double)ts.tv_nsec/1e6;
#endif
}
/* Check all work, including generation/dedup/refinement, at bounded intervals.
   Phase exhaustion is scheduling only, never a global exhaustion flag. */
static int stopped(Search *s) {
    if(s->time_stop||s->candidate_stop||s->phase_stop)return 1;
    double now=op3_search_now_ms();
    if(now>=s->deadline){s->time_stop=1;return 1;}
    if(s->count>=s->r->options.max_candidates){s->candidate_stop=1;return 1;}
    if(now>=s->phase_deadline||s->count>=s->phase_limit){s->phase_stop=1;return 1;}
    return 0;
}
static unsigned random_u32(Search *s) { unsigned x=s->rng;x^=x<<13;x^=x>>17;x^=x<<5;return s->rng=x; }
static double dot(const double a[3],const double b[3]) { return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]; }
static void cross(const double a[3],const double b[3],double c[3]) { c[0]=a[1]*b[2]-a[2]*b[1];c[1]=a[2]*b[0]-a[0]*b[2];c[2]=a[0]*b[1]-a[1]*b[0]; }
static int unit(double v[3]) { double n=sqrt(dot(v,v));if(!(n>1e-14))return 0;for(int k=0;k<3;k++)v[k]/=n;return 1; }
static void multiply(const double a[4],const double b[4],double q[4]) {
    double v[4]={a[3]*b[0]+a[0]*b[3]+a[1]*b[2]-a[2]*b[1],a[3]*b[1]-a[0]*b[2]+a[1]*b[3]+a[2]*b[0],a[3]*b[2]+a[0]*b[1]-a[1]*b[0]+a[2]*b[3],a[3]*b[3]-a[0]*b[0]-a[1]*b[1]-a[2]*b[2]};
    memcpy(q,v,sizeof v);
}
static void rotate(const double q[4],int axis,double angle,double result[4]) {
    double r[4]={0,0,0,cos(angle/2)};r[axis]=sin(angle/2);multiply(r,q,result);
}
static void matrix_quaternion(double m[3][3],double q[4]) {
    double t=m[0][0]+m[1][1]+m[2][2];
    if(t>0) {
        double s=sqrt(1+t)*2;q[3]=s/4;q[0]=(m[2][1]-m[1][2])/s;q[1]=(m[0][2]-m[2][0])/s;q[2]=(m[1][0]-m[0][1])/s;
    } else {
        int i=m[1][1]>m[0][0]?1:0;if(m[2][2]>m[i][i])i=2;
        int j=(i+1)%3,k=(i+2)%3;double s=sqrt(fmax(0,1+m[i][i]-m[j][j]-m[k][k]))*2;
        q[i]=s/4;q[j]=(m[j][i]+m[i][j])/s;q[k]=(m[k][i]+m[i][k])/s;q[3]=(m[k][j]-m[j][k])/s;
    }
}
static double box_volume(const Op3Box *b) { return b->width*b->length*b->height; }
static void summarize(const Op3Request *r,Op3Result *result) {
    unsigned char used[OP3_MAX_ITEMS]={0};double packed=0,volume=0;result->total_cost=0;
    for(int i=0;i<result->placement_count;i++) {
        const Op3Item *a=&r->items[result->placements[i].item_index];
        used[result->placements[i].item_index]=1;packed+=a->width*a->length*a->height;
    }
    for(int i=0;i<result->bin_count;i++) {
        const Op3Box *b=&r->boxes[result->bins[i].box_index];volume+=box_volume(b);result->total_cost+=b->cost;
    }
    result->unpacked_count=0;
    for(int i=0;i<r->item_count;i++)if(!used[i])result->unpacked[result->unpacked_count++]=i;
    result->utilization=volume>0?packed/volume:0;
}
static int better(const Op3Request *r,const Op3Result *a,const Op3Result *b) {
    if(a->placement_count!=b->placement_count)return a->placement_count>b->placement_count;
    if(a->total_cost!=b->total_cost)return a->total_cost<b->total_cost;
    if(a->bin_count!=b->bin_count)return a->bin_count<b->bin_count;
    double av=0,bv=0;
    for(int i=0;i<a->bin_count;i++)av+=box_volume(&r->boxes[a->bins[i].box_index]);
    for(int i=0;i<b->bin_count;i++)bv+=box_volume(&r->boxes[b->bins[i].box_index]);
    return av<bv;
}
static void incumbent(Search *s,Layout *layout) {
    summarize(s->r,&layout->result);
    if(better(s->r,&layout->result,s->best))*s->best=layout->result;
}
/* Canonical solid signature: independently reverse local axes, then sort
   equal-side columns. This removes cuboid symmetries without treating world
   reflections or different product permissions as equivalent rotations. */
static void describe(const Op3Item *item,const Op3Box *box,double clearance,const double q[4],Orientation *o) {
    double n=sqrt(q[0]*q[0]+q[1]*q[1]+q[2]*q[2]+q[3]*q[3]);
    for(int k=0;k<4;k++)o->q[k]=q[k]/n;
    double x=o->q[0],y=o->q[1],z=o->q[2],w=o->q[3];
    double m[3][3]={{1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)},{2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)},{2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)}};
    memcpy(o->m,m,sizeof m);
    double sides[3]={item->width,item->length,item->height},b[3]={box->width,box->length,box->height};
    o->rank=0;double fill=1;
    for(int k=0;k<3;k++) {
        o->extent[k]=0;for(int j=0;j<3;j++)o->extent[k]+=fabs(m[k][j])*sides[j]/2;
        double ratio=(2*o->extent[k]+2*clearance)/b[k];
        o->rank+=fmax(0,ratio-1)*1000;fill*=ratio;
    }
    o->rank+=fill;
    for(int j=0;j<3;j++) {
        int sign=1;for(int k=0;k<3;k++)if(fabs(m[k][j])>1e-12){sign=m[k][j]<0?-1:1;break;}
        o->key[4*j]=sides[j];for(int k=0;k<3;k++)o->key[4*j+1+k]=sign*m[k][j];
    }
    for(int j=1;j<3;j++)for(int i=j;i>0;i--) {
        int cmp=0;for(int k=0;k<4;k++)if(o->key[4*(i-1)+k]!=o->key[4*i+k]){cmp=o->key[4*(i-1)+k]>o->key[4*i+k];break;}
        if(!cmp)break;
        for(int k=0;k<4;k++){double v=o->key[4*i+k];o->key[4*i+k]=o->key[4*(i-1)+k];o->key[4*(i-1)+k]=v;}
    }
}
static int equivalent(const Orientation *a,const Orientation *b) {
    for(int k=0;k<12;k++)if(fabs(a->key[k]-b->key[k])>1e-10)return 0;
    return 1;
}
static void orientation_add(Search *s,const Op3Item *a,const Op3Box *b,const double q[4],Orientation *all,int *count) {
    if(stopped(s))return;
    Orientation o;describe(a,b,s->r->options.clearance,q,&o);
    for(int i=0;i<*count;i++)if(equivalent(&o,&all[i]))return;
    int at=*count;
    if(at==ORIENTATIONS){if(o.rank>=all[at-1].rank)return;at--;}
    else (*count)++;
    while(at>0&&o.rank<all[at-1].rank){all[at]=all[at-1];at--;}
    all[at]=o;
}
static void direction_quaternion(const double direction[3],int long_axis,double spin,double q[4]) {
    double x[3]={direction[0],direction[1],direction[2]};unit(x);
    int least=0;for(int k=1;k<3;k++)if(fabs(x[k])<fabs(x[least]))least=k;
    double ref[3]={0},y[3],z[3];ref[least]=1;cross(x,ref,y);unit(y);cross(x,y,z);
    double m[3][3];int second=(long_axis+1)%3,third=(long_axis+2)%3;
    for(int k=0;k<3;k++) {m[k][long_axis]=x[k];m[k][second]=cos(spin)*y[k]+sin(spin)*z[k];m[k][third]=-sin(spin)*y[k]+cos(spin)*z[k];}
    matrix_quaternion(m,q);
}
static int orientations(Search *s,const Layout *layout,int bin,int ii,int bi,Orientation *all) {
    const Op3Item *a=&s->r->items[ii];const Op3Box *b=&s->r->boxes[bi];int count=0;
    const double bases[6][4]={{0,0,0,1},{1,0,0,0},{0,.7071067811865475244,0,.7071067811865475244},{0,-.7071067811865475244,0,.7071067811865475244},{.7071067811865475244,0,0,.7071067811865475244},{-.7071067811865475244,0,0,.7071067811865475244}};
    int faces=a->rotation>=OP3_ANY?6:1;
    for(int f=0;f<faces&&!stopped(s);f++) {
        int angles=a->rotation==OP3_NONE?1:a->diagonal?(int)ceil(180/s->r->options.angle_step):2;
        for(int j=0;j<angles&&!stopped(s);j++) {
            double q[4];rotate(bases[f],2,(a->diagonal?j*s->r->options.angle_step:90*j)*PI/180,q);
            orientation_add(s,a,b,q,all,&count);
        }
    }
    if(s->tilted&&a->rotation==OP3_FREE3D) {
        /* Reuse neighbors' attitudes to discover parallel contacts. */
        for(int i=0;i<layout->result.placement_count&&!stopped(s);i++)if(layout->result.placements[i].bin_index==bin)
            orientation_add(s,a,b,layout->result.placements[i].pose.orientation,all,&count);
        double sides[3]={a->width,a->length,a->height};int longest=0;
        for(int k=1;k<3;k++)if(sides[k]>sides[longest])longest=k;
        double dim[3]={b->width-2*s->r->options.clearance,b->length-2*s->r->options.clearance,b->height-2*s->r->options.clearance};
        for(int variant=0;variant<3&&!stopped(s);variant++)for(int x=0;x<=1&&!stopped(s);x++)for(int y=-1;y<=1&&!stopped(s);y++)for(int z=-1;z<=1&&!stopped(s);z++) {
            if(!x&&!y&&!z)continue;
            double v[3]={x*(variant==0?1:dim[0]),y*(variant==0?1:dim[1]),z*(variant==0?1:dim[2])};
            if(variant==2)for(int k=0;k<3;k++)v[k]=copysign(sqrt(fabs(v[k])),v[k]);
            if(!unit(v))continue;
            for(int spin=0;spin<8&&!stopped(s);spin++) {double q[4];direction_quaternion(v,longest,spin*PI/8,q);orientation_add(s,a,b,q,all,&count);}
        }
        /* Deterministic low-discrepancy unit quaternions, not an Euler grid. */
        for(int i=0;i<96&&!stopped(s);i++) {
            double u=(i+.5)/96,v=fmod((i+1)*.6180339887498948482,1),w=fmod((i+1)*.4142135623730950488,1);
            double q[4]={sqrt(1-u)*sin(2*PI*v),sqrt(1-u)*cos(2*PI*v),sqrt(u)*sin(2*PI*w),sqrt(u)*cos(2*PI*w)};
            orientation_add(s,a,b,q,all,&count);
        }
    }
    /* Refine overflow/packing extents continuously, including XY control.
       Every winning move becomes a normal orientation and undergoes the same
       full pose validator later. Keep several basins to avoid one local path. */
    if(a->rotation!=OP3_NONE&&a->diagonal) {
        int basins=count<6?count:6;
        for(int i=0;i<basins&&!stopped(s);i++) {
            Orientation best=all[i];double step=s->r->options.angle_step*PI/180;
            for(int level=0;level<12&&!stopped(s);level++,step*=.5) {
                for(int pass=0;pass<2&&!stopped(s);pass++) {
                    int first=s->tilted&&a->rotation==OP3_FREE3D?0:2;
                    for(int axis=first;axis<3&&!stopped(s);axis++)for(int sign=-1;sign<=1;sign+=2) {
                        double q[4];Orientation trial;rotate(best.q,axis,sign*step,q);describe(a,b,s->r->options.clearance,q,&trial);
                        if(trial.rank<best.rank){best=trial;orientation_add(s,a,b,q,all,&count);}
                    }
                }
            }
        }
    }
    return count;
}
static double radius(const Orientation *o,const Op3Item *a,const double n[3],double clearance) {
    double sides[3]={a->width,a->length,a->height},r=0;
    for(int j=0;j<3;j++){double axis[3]={o->m[0][j],o->m[1][j],o->m[2][j]};r+=fabs(dot(n,axis))*(sides[j]+clearance)/2;}
    return r;
}
static void center_add(Search *s,const double v[3],const double lo[3],const double hi[3],Center *all,int *count) {
    if(stopped(s))return;
    Center c={{v[0],v[1],v[2]},0};
    for(int k=0;k<3;k++) {
        if(!isfinite(v[k])||v[k]<lo[k]-1e-10||v[k]>hi[k]+1e-10)return;
        c.v[k]=fmax(lo[k],fmin(hi[k],c.v[k]));
        c.rank+=(c.v[k]-lo[k])/(hi[k]-lo[k]+1e-4)*(k==2?1.15:1);
    }
    double scale=fmax(hi[0],fmax(hi[1],hi[2]));double tolerance=DBL_EPSILON*fmax(scale,1e-4)*8;
    for(int i=0;i<*count;i++)if(fabs(c.v[0]-all[i].v[0])<=tolerance&&fabs(c.v[1]-all[i].v[1])<=tolerance&&fabs(c.v[2]-all[i].v[2])<=tolerance)return;
    int at=*count;
    if(at==CENTERS){if(c.rank>=all[at-1].rank)return;at--;}
    else (*count)++;
    while(at>0&&c.rank<all[at-1].rank){all[at]=all[at-1];at--;}
    all[at]=c;
}
static int intersection(const Plane *a,const Plane *b,const Plane *c,double v[3]) {
    double bc[3],ca[3],ab[3];cross(b->n,c->n,bc);double determinant=dot(a->n,bc);
    if(fabs(determinant)<1e-10)return 0;
    cross(c->n,a->n,ca);cross(a->n,b->n,ab);
    for(int k=0;k<3;k++)v[k]=(a->d*bc[k]+b->d*ca[k]+c->d*ab[k])/determinant;
    return 1;
}
static int centers(Search *s,const Layout *layout,int bin,const Op3Item *a,const Op3Box *box,const Orientation *o,Center *all) {
    double b[3]={box->width,box->length,box->height},lo[3],hi[3];int count=0;
    for(int k=0;k<3;k++){lo[k]=o->extent[k]+s->r->options.clearance;hi[k]=b[k]-lo[k];if(lo[k]>hi[k])return 0;}
    /* Bounds contacts and the box center, rather than a spatial grid. */
    for(int mask=0;mask<8;mask++) {double v[3];for(int k=0;k<3;k++)v[k]=(mask&(1<<k))?hi[k]:lo[k];center_add(s,v,lo,hi,all,&count);}
    double middle[3]={b[0]/2,b[1]/2,b[2]/2};center_add(s,middle,lo,hi,all,&count);
    Plane planes[OP3_PLANES];int np=0;
    for(int k=0;k<3;k++)for(int side=0;side<2;side++){Plane p={{0},side?hi[k]:lo[k]};p.n[k]=1;planes[np++]=p;}
    /* Contact planes from both solids' face normals. Their intersections with
       walls and each other generate finite candidate positions for oblique
       parallel/skew contacts. Subsequent SAT, including all edge-cross axes,
       alone decides validity. Limit neighbors deterministically per restart. */
    for(int p=0;p<layout->result.placement_count&&!stopped(s)&&np+12<=OP3_PLANES;p++) {
        int j=(s->run&1)?layout->result.placement_count-1-p:p;
        if(layout->result.placements[j].bin_index!=bin)continue;
        const Op3Obb *other=&layout->obbs[j];
        for(int source=0;source<2;source++)for(int axis=0;axis<3;axis++) {
            double n[3];for(int k=0;k<3;k++)n[k]=source?o->m[k][axis]:(double)other->matrix[k][axis];
            double distance=0,projection=0;
            for(int k=0;k<3;k++)projection+=n[k]*(double)other->center[k];
            for(int k=0;k<3;k++) {double v=0;for(int t=0;t<3;t++)v+=n[t]*(double)other->matrix[t][k];distance+=fabs(v)*((double)other->half[k]+s->r->options.clearance/2);}
            distance+=radius(o,a,n,s->r->options.clearance);
            for(int sign=-1;sign<=1;sign+=2) {
                Plane plane={{n[0],n[1],n[2]},projection+sign*distance};planes[np++]=plane;
                /* A face contact through a neighbor center also supplies a
                   useful point when only one wall is reachable. */
                double v[3],offset=plane.d-dot(n,middle);
                for(int k=0;k<3;k++)v[k]=middle[k]+offset*n[k];
                center_add(s,v,lo,hi,all,&count);
            }
        }
    }
    for(int i=0;i<np&&!stopped(s);i++)for(int j=i+1;j<np&&!stopped(s);j++)for(int k=j+1;k<np&&!stopped(s);k++) {
        if(k<6)continue;
        double v[3];if(intersection(&planes[i],&planes[j],&planes[k],v))center_add(s,v,lo,hi,all,&count);
    }
    return count;
}
/* EXACT emitted double pose is canonicalized first, then cached and checked.
   No pose is accepted using the nominal generation matrix/bounds. */
static int validate_pose(Search *s,const Layout *layout,int bin,const Op3Box *box,const Op3Pose *proposed,Pick *pick) {
    if(stopped(s))return 0;
    s->count++;
    if(op3_pose_canonicalize(proposed,&pick->pose)!=OP3_OK)return 0;
    if(op3_obb_build(&pick->pose,&pick->obb)!=OP3_OK)return 0;
    int inside=0;double b[3]={box->width,box->length,box->height};
    if(op3_obb_inside(&pick->obb,b,s->r->options.clearance,&inside)!=OP3_OK||!inside)return 0;
    for(int i=0;i<layout->result.placement_count;i++)if(layout->result.placements[i].bin_index==bin) {
        int overlap=1;
        if(op3_obb_intersects(&pick->obb,&layout->obbs[i],s->r->options.clearance,&overlap)!=OP3_OK||overlap)return 0;
    }
    pick->valid=1;return 1;
}
static double pose_rank(const Pick *p,const Op3Box *b) {
    return ((double)p->obb.aabb[0][1])/b->width+((double)p->obb.aabb[1][1])/b->length+1.15*((double)p->obb.aabb[2][1])/b->height;
}
static int weight_fits(const Layout *layout,int bin,const Op3Item *item,const Op3Box *box,const Op3Request *r) {
    if(box->max_weight==0)return item->weight==0;
    double upper=item->weight;int terms=1;
    for(int i=0;i<layout->result.placement_count;i++)if(layout->result.placements[i].bin_index==bin) {
        double weight=r->items[layout->result.placements[i].item_index].weight;
        if(weight)upper=nextafter(upper+weight,INFINITY);
        terms++;
    }
    /* Round the sum upward and the capacity allowance downward, using binary64
       even under a 53-bit caller. Using capacity rather than max(sum,capacity)
       is conservative near the boundary; no arithmetic error can enlarge the
       independent verifier's relative allowance. Zero is handled above. */
    double allowance=nextafter(2*DBL_EPSILON*(terms+2)*box->max_weight,-INFINITY);
    double limit=nextafter(box->max_weight+allowance,-INFINITY);
    return upper<=limit;
}
static void pick_add(Pick picks[PICKS],const Pick *pick) {
    for(int i=0;i<PICKS;i++)if(picks[i].valid) {
        double distance=0;for(int k=0;k<3;k++)distance+=fabs(picks[i].pose.center[k]-pick->pose.center[k]);
        double rotation=0;for(int k=0;k<4;k++)rotation+=fabs(picks[i].pose.orientation[k]-pick->pose.orientation[k]);
        if(distance<1e-10&&rotation<1e-10)return;
    }
    int at=PICKS-1;if(picks[at].valid&&pick->rank>=picks[at].rank)return;
    while(at>0&&(!picks[at-1].valid||pick->rank<picks[at-1].rank)){picks[at]=picks[at-1];at--;}
    picks[at]=*pick;
}
static void refine_placement(Search *s,const Layout *layout,int bin,const Op3Item *a,const Op3Box *b,Pick picks[PICKS]) {
    /* Coupled continuous quaternion and position refinement. Reproject against
       bounds for each attitude, plus independent translations; validate every
       new pose. Restricted items rotate only about world Z after face choice. */
    if(picks[0].valid&&a->rotation!=OP3_NONE&&a->diagonal) {
        Pick best=picks[0];double angular=s->r->options.angle_step*PI/180;
        double positional=fmin(b->width,fmin(b->length,b->height))*.04;
        for(int level=0;level<5&&!stopped(s);level++,angular*=.5,positional*=.5) {
            int first=s->tilted&&a->rotation==OP3_FREE3D?0:2;
            for(int axis=first;axis<3&&!stopped(s);axis++)for(int sign=-1;sign<=1;sign+=2) {
                Op3Pose pose=best.pose;rotate(best.pose.orientation,axis,sign*angular,pose.orientation);
                Orientation o;describe(a,b,s->r->options.clearance,pose.orientation,&o);
                double dim[3]={b->width,b->length,b->height};int fits=1;
                for(int k=0;k<3;k++) {
                    double lo=o.extent[k]+s->r->options.clearance,hi=dim[k]-lo;if(lo>hi){fits=0;break;}
                    pose.center[k]=fmax(lo,fmin(hi,pose.center[k]+(o.extent[k]-(double)(best.obb.aabb[k][1]-best.obb.aabb[k][0])/2)));
                }
                Pick trial={0};if(fits&&validate_pose(s,layout,bin,b,&pose,&trial)){trial.rank=pose_rank(&trial,b);if(trial.rank<best.rank){best=trial;pick_add(picks,&trial);}}
            }
            for(int axis=0;axis<3&&!stopped(s);axis++)for(int sign=-1;sign<=1;sign+=2) {
                Op3Pose pose=best.pose;pose.center[axis]+=sign*positional;
                Pick trial={0};if(validate_pose(s,layout,bin,b,&pose,&trial)){trial.rank=pose_rank(&trial,b);if(trial.rank<best.rank){best=trial;pick_add(picks,&trial);}}
            }
        }
    }
}
static void find_placements(Search *s,const Layout *layout,int bin,int ii,int bi,Pick picks[PICKS]) {
    memset(picks,0,PICKS*sizeof *picks);
    const Op3Item *a=&s->r->items[ii];const Op3Box *b=&s->r->boxes[bi];
    if(!weight_fits(layout,bin,a,b,s->r))return;
    Orientation all[ORIENTATIONS];int no=orientations(s,layout,bin,ii,bi,all);
    int feasible=0;
    for(int i=0;i<no&&!stopped(s);i++) {
        Orientation *o=&all[i];
        if(o->extent[0]*2+2*s->r->options.clearance>b->width||o->extent[1]*2+2*s->r->options.clearance>b->length||o->extent[2]*2+2*s->r->options.clearance>b->height)continue;
        Center points[CENTERS];int nc=centers(s,layout,bin,a,b,o,points);feasible++;
        int accepted=0;
        for(int j=0;j<nc&&!stopped(s);j++) {
            Op3Pose pose={a->width,a->length,a->height,{0},{0}};memcpy(pose.center,points[j].v,sizeof pose.center);memcpy(pose.orientation,o->q,sizeof pose.orientation);
            Pick trial={0};
            if(validate_pose(s,layout,bin,b,&pose,&trial)){trial.rank=pose_rank(&trial,b);pick_add(picks,&trial);accepted++;}
            if(accepted>=PICKS+1)break;
        }
        if(picks[0].valid&&feasible>=8)break;
    }
    refine_placement(s,layout,bin,a,b,picks);
}

static double order_key(const Op3Item *a,int mode) {
    double longest=fmax(a->width,fmax(a->length,a->height)),smallest=fmin(a->width,fmin(a->length,a->height));
    switch(mode%4){case 0:return longest;case 1:return a->width*a->length*a->height;case 2:return a->weight;default:return longest/smallest;}
}
static void make_orders(Search *s) {
    for(int run=0;run<s->r->options.restarts&&!stopped(s);run++) {
        int *order=s->orders[run];for(int i=0;i<s->r->item_count;i++)order[i]=i;
        for(int i=1;i<s->r->item_count&&!stopped(s);i++) {int v=order[i],j=i-1;while(j>=0&&order_key(&s->r->items[order[j]],run)<order_key(&s->r->items[v],run)){order[j+1]=order[j];j--;}order[j+1]=v;}
        if(run>=4)for(int i=s->r->item_count-1;i>0;i--){int j=(int)(random_u32(s)%(unsigned)(i+1));int v=order[i];order[i]=order[j];order[j]=v;}
    }
}
static uint64_t box_mask(const Layout *layout) {
    uint64_t mask=0;for(int i=0;i<layout->result.bin_count;i++)mask|=UINT64_C(1)<<layout->result.bins[i].box_index;
    return mask;
}
static int layout_better(Search *s,const Layout *a,const Layout *b) {
    if(better(s->r,&a->result,&b->result))return 1;
    if(better(s->r,&b->result,&a->result))return 0;
    return a->compact<b->compact;
}
static void beam_add(Search *s,Layout *next,int *count,const Layout *trial) {
    /* Preserve alternative box portfolios even if their current prefix costs
       more; they can avoid a future additional bin. Third slot also retains
       a different geometric arrangement of the best portfolio. */
    uint64_t mask=box_mask(trial);int at=*count;
    if(at==BEAM) {
        at=BEAM-1;
        for(int i=0;i<BEAM;i++)if(box_mask(&next[i])==mask){at=i;break;}
        if(!layout_better(s,trial,&next[at]))return;
    } else (*count)++;
    next[at]=*trial;
    /* Sorting large caches is unnecessary: find the best slot only when used. */
}
static void append(Layout *trial,int bin,int bi,int ii,const Pick *pick,const Op3Request *r) {
    if(bin==trial->result.bin_count) {
        trial->result.bins[bin]=(Op3Bin){bi,0};trial->result.bin_count++;
        if(trial->stock[bi]>0)trial->stock[bi]--;
    }
    int at=trial->result.placement_count++;
    trial->result.placements[at]=(Op3Placement){ii,bin,pick->pose};trial->obbs[at]=pick->obb;trial->used[ii]=1;
    trial->result.bins[bin].weight+=r->items[ii].weight;trial->compact+=pick->rank;
}
int op3_search(const Op3Request *r,Op3Result *out,double start) {
    Search s={0};s.r=r;s.best=out;s.start=start;s.deadline=start+r->options.time_limit_ms;s.phase_deadline=s.deadline;s.phase_limit=r->options.max_candidates;s.rng=r->options.seed?r->options.seed:0x6d2b79f5;
    summarize(r,out);
    if(!r->item_count){out->elapsed_ms=op3_search_now_ms()-start;out->stop_reason=OP3_COMPLETED;return 0;}
    Layout *memory=calloc(BEAM*2+1,sizeof *memory);
    if(!memory)return 1;
    Layout *beam=memory,*next=memory+BEAM,*trial=memory+BEAM*2;
    int has3d=0;for(int i=0;i<r->item_count;i++)if(r->items[i].rotation==OP3_FREE3D)has3d=1;
    make_orders(&s);
    for(int phase=0;phase<=has3d&&!s.time_stop&&!s.candidate_stop;phase++) {
        s.tilted=phase;s.phase_stop=0;
        s.phase_deadline=has3d&&!phase?start+r->options.time_limit_ms*.25:s.deadline;
        s.phase_limit=has3d&&!phase?r->options.max_candidates/4:r->options.max_candidates;
        double phase_start=op3_search_now_ms();
        for(s.run=0;s.run<r->options.restarts&&!stopped(&s);s.run++) {
            if(s.run+1>s.runs)s.runs=s.run+1;
            memset(beam,0,BEAM*sizeof *beam);int nb=1;
            for(int bi=0;bi<r->box_count;bi++)beam[0].stock[bi]=r->boxes[bi].quantity;
            for(int depth=0;depth<r->item_count&&!stopped(&s);depth++) {
                int ii=s.orders[s.run][depth],nn=0;
                for(int state=0;state<nb&&!stopped(&s);state++) {
                    Layout *base=&beam[state];int added=0;
                    for(int bin=0;bin<=base->result.bin_count&&!stopped(&s);bin++) {
                        int fresh=bin==base->result.bin_count;
                        int first=fresh?0:base->result.bins[bin].box_index,last=fresh?r->box_count:first+1;
                        for(int bi=first;bi<last&&!stopped(&s);bi++) {
                            if(fresh&&!base->stock[bi])continue;
                            Pick picks[PICKS];find_placements(&s,base,bin,ii,bi,picks);
                            /* Even a stop during refinement cannot discard a
                               previously validated placement from this call. */
                            for(int p=0;p<PICKS;p++)if(picks[p].valid) {
                                *trial=*base;append(trial,bin,bi,ii,&picks[p],r);incumbent(&s,trial);beam_add(&s,next,&nn,trial);added=1;
                            }
                        }
                    }
                    if(!added){*trial=*base;incumbent(&s,trial);beam_add(&s,next,&nn,trial);}
                }
                if(nn){Layout *swap=beam;beam=next;next=swap;nb=nn;}
            }
        }
        if(has3d&&!phase){s.xy_count=s.count;s.xy_ms=op3_search_now_ms()-phase_start;}
    }
    /* incumbent copies carry only geometric/layout statistics. Add all global
       diagnostics once, so later improvements cannot erase a prior stop. */
    free(memory);summarize(r,out);out->elapsed_ms=op3_search_now_ms()-start;out->candidates=s.count;out->restarts=s.runs;
    out->timed_out=s.time_stop;out->budget_exhausted=s.candidate_stop;
    out->stop_reason=s.time_stop?OP3_TIME_LIMIT:s.candidate_stop?OP3_CANDIDATE_LIMIT:out->unpacked_count?OP3_SEARCH_EXHAUSTED:OP3_COMPLETED;
    out->xy_candidates=s.xy_count;out->xy_elapsed_ms=s.xy_ms;
    return 0;
}

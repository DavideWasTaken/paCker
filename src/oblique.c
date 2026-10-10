#define _POSIX_C_SOURCE 200809L
#include "oblique.h"
#include <math.h>
#include <float.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <time.h>
#endif
#define EPS 1e-9
#define PI 3.14159265358979323846
#define ANCHORS (OP_MAX_ITEMS*5+4)
#if defined(_MSC_VER)
#define OP_NOINLINE __declspec(noinline)
#elif defined(__GNUC__) || defined(__clang__)
#define OP_NOINLINE __attribute__((noinline))
#else
#define OP_NOINLINE
#endif
typedef struct { double c,s,hx,hy; } Shape;
static double geometric_epsilon(const OpPlacement *p) {
    return EPS*fmin(1,fmin(p->width,fmin(p->length,p->height)));
}
static Shape shape(const OpPlacement *p) {
    Shape s={0,0,0,0};
    /* Exact axis-aligned poses need exact axes. A residual cos(90deg) times
       a long side can otherwise exceed the thin side's geometric epsilon. */
    double turn=p->angle;
    if(turn<0||turn>=360){turn=fmod(turn,360);if(turn<0)turn+=360;}
    if(turn==0){s.c=1;s.s=0;}
    else if(turn==90){s.c=0;s.s=1;}
    else if(turn==180){s.c=-1;s.s=0;}
    else if(turn==270){s.c=0;s.s=-1;}
    else {double a=p->angle*PI/180;s.c=cos(a);s.s=sin(a);}
    s.hx=(fabs(s.c)*p->width+fabs(s.s)*p->length)/2;
    s.hy=(fabs(s.s)*p->width+fabs(s.c)*p->length)/2;
    return s;
}
double op_now_ms(void) {
#ifdef _WIN32
    LARGE_INTEGER f,t; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&t);
    return (double)t.QuadPart*1000/(double)f.QuadPart;
#else
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    return (double)t.tv_sec*1000+(double)t.tv_nsec/1e6;
#endif
}
void op_default_options(OpOptions *o) { *o=(OpOptions){15,1000,0,200000,42,8,OP_SUPPORT_CONTACT,0}; }
int op_inside(const OpPlacement *p,const OpBox *b,double gap) {
    Shape s=shape(p);
    double e=geometric_epsilon(p);
    return p->x-s.hx>=gap-e && p->y-s.hy>=gap-e && p->z>=-e &&
        p->x+s.hx<=b->width-gap+e && p->y+s.hy<=b->length-gap+e && p->z+p->height<=b->height+e;
}
int op_intersects(const OpPlacement *a,const OpPlacement *b,double gap) {
    double e=fmin(geometric_epsilon(a),geometric_epsilon(b));
    if(a->z+a->height<=b->z+e || b->z+b->height<=a->z+e)return 0;
    Shape u=shape(a),v=shape(b);
    double axes[4][2]={{u.c,u.s},{-u.s,u.c},{v.c,v.s},{-v.s,v.c}};
    for(int i=0;i<4;i++) {
        double x=axes[i][0],y=axes[i][1];
        double ra=(fabs(x*u.c+y*u.s)*a->width+fabs(-x*u.s+y*u.c)*a->length)/2;
        double rb=(fabs(x*v.c+y*v.s)*b->width+fabs(-x*v.s+y*v.c)*b->length)/2;
        if(fabs((a->x-b->x)*x+(a->y-b->y)*y)>=ra+rb+gap-e)return 0;
    }
    return 1;
}
typedef struct { long double x,y; } SupportPoint;
/* Clip a top-face polygon in the candidate's normalized local frame. This
   keeps area calculations near unity even for tiny or very long products. */
static int support_polygon(const OpPlacement *p,Shape a,const OpPlacement *q,SupportPoint *result) {
    Shape b=shape(q);SupportPoint poly[16],next[16];int n=4;
    if((a.c==0||a.s==0)&&(b.c==0||b.s==0)) {
        long double dx=(long double)q->x-p->x,dy=(long double)q->y-p->y;
        long double cx=dx*a.c+dy*a.s,cy=-dx*a.s+dy*a.c;
        long double hx=a.c==0?b.hy:b.hx,hy=a.c==0?b.hx:b.hy;
        long double left=fmaxl(-.5L,(cx-hx)/p->width),right=fminl(.5L,(cx+hx)/p->width);
        long double bottom=fmaxl(-.5L,(cy-hy)/p->length),top=fminl(.5L,(cy+hy)/p->length);
        if(left>right||bottom>top)return 0;
        result[0]=(SupportPoint){left,bottom};result[1]=(SupportPoint){right,bottom};
        result[2]=(SupportPoint){right,top};result[3]=(SupportPoint){left,top};return 4;
    }
    const int signs[4][2]={{-1,-1},{1,-1},{1,1},{-1,1}};
    for(int k=0;k<4;k++) {
        long double dx=(long double)q->x-p->x+b.c*signs[k][0]*(long double)q->width/2-b.s*signs[k][1]*(long double)q->length/2;
        long double dy=(long double)q->y-p->y+b.s*signs[k][0]*(long double)q->width/2+b.c*signs[k][1]*(long double)q->length/2;
        poly[k]=(SupportPoint){(dx*a.c+dy*a.s)/p->width,(-dx*a.s+dy*a.c)/p->length};
    }
    for(int edge=0;edge<4 && n;edge++) {
        int m=0,axis=edge/2;long double sign=edge%2?1:-1;
        for(int k=0;k<n;k++) {
            SupportPoint u=poly[(k+n-1)%n],v=poly[k];
            long double du=0.5L-sign*(axis?u.y:u.x),dv=0.5L-sign*(axis?v.y:v.x);
            if((du>=0)!=(dv>=0)) {
                long double t=du/(du-dv);
                next[m++]=(SupportPoint){u.x+t*(v.x-u.x),u.y+t*(v.y-u.y)};
            }
            if(dv>=0)next[m++]=v;
        }
        memcpy(poly,next,(size_t)m*sizeof *poly);n=m;
    }
    memcpy(result,poly,(size_t)n*sizeof *poly);return n;
}
typedef struct { SupportPoint points[16];int count,rectangle; } SupportFace;
typedef struct { long double lo,hi; } SupportInterval;
static int cmp_long_double(const void *a,const void *b) {
    long double x=*(const long double*)a,y=*(const long double*)b;return (x>y)-(x<y);
}
static int cmp_support_interval(const void *a,const void *b) {
    const SupportInterval *x=a,*y=b;return (x->lo>y->lo)-(x->lo<y->lo);
}
static int support_section(const SupportFace *faces,int count,long double x,long double tolerance) {
    SupportInterval intervals[OP_MAX_ITEMS];int n=0;
    for(int i=0;i<count;i++) {
        const SupportFace *f=&faces[i];long double lo=1,hi=-1;
        if(f->rectangle) {
            if(x>=fminl(f->points[0].x,f->points[1].x)&&x<=fmaxl(f->points[0].x,f->points[1].x))
                intervals[n++]=(SupportInterval){fminl(f->points[0].y,f->points[2].y),fmaxl(f->points[0].y,f->points[2].y)};
            continue;
        }
        for(int j=0;j<f->count;j++) {
            SupportPoint u=f->points[j],v=f->points[(j+1)%f->count];
            if(x<fminl(u.x,v.x)||x>fmaxl(u.x,v.x))continue;
            if(u.x==v.x){lo=fminl(lo,fminl(u.y,v.y));hi=fmaxl(hi,fmaxl(u.y,v.y));}
            else {
                long double y=u.y+(x-u.x)/(v.x-u.x)*(v.y-u.y);
                lo=fminl(lo,y);hi=fmaxl(hi,y);
            }
        }
        if(hi>=lo)intervals[n++]=(SupportInterval){lo,hi};
    }
    qsort(intervals,(size_t)n,sizeof *intervals,cmp_support_interval);
    long double covered=-.5L;
    for(int i=0;i<n;i++) {
        if(intervals[i].lo>covered+tolerance)return 0;
        covered=fmaxl(covered,intervals[i].hi);
        if(covered>=.5L-tolerance)return 1;
    }
    return 0;
}
/* Positional coverage, not an area-percentage test: a long thin footprint
   must not bridge a visible gap merely because its missing area is small.
   Disjoint top-face interiors imply that edge order cannot cross within a
   slab between polygon vertices. Endpoints plus midpoint detect holes and
   vertex-only contacts, using tolerance on each physical coordinate. */
/* Keep the large polygon frame out of the common exact-rectangle path. */
static OP_NOINLINE int support_polygon_union(const OpPlacement *p,Shape a,const OpPlacement *placed,int count,double e) {
    SupportFace faces[OP_MAX_ITEMS];int nf=0,nx=2;
    long double xs[OP_MAX_ITEMS*16+2];xs[0]=-.5L;xs[1]=.5L;
    for(int i=0;i<count;i++)if(fabs(p->z-placed[i].z-placed[i].height)<=e) {
        SupportFace *f=&faces[nf];f->count=support_polygon(p,a,&placed[i],f->points);
        if(!f->count)continue;
        f->rectangle=f->count==4&&f->points[0].y==f->points[1].y&&f->points[1].x==f->points[2].x&&
                     f->points[2].y==f->points[3].y&&f->points[3].x==f->points[0].x;
        for(int j=0;j<f->count;j++)xs[nx++]=f->points[j].x;
        nf++;
    }
    if(!nf)return 0;
    qsort(xs,(size_t)nx,sizeof *xs,cmp_long_double);
    long double xtol=(long double)e/p->width,ytol=(long double)e/p->length;
    for(int i=1;i<nx;i++) {
        if(xs[i]-xs[i-1]<=xtol)continue;
        if(!support_section(faces,nf,xs[i-1],ytol)||
           !support_section(faces,nf,(xs[i-1]+xs[i])/2,ytol)||
           !support_section(faces,nf,xs[i],ytol))return 0;
    }
    return 1;
}
typedef struct { long double left,right,bottom,top; } SupportRectangle;
static int support_rectangle_section(const SupportRectangle *faces,int count,long double x,long double tolerance) {
    SupportInterval intervals[OP_MAX_ITEMS];int n=0;
    for(int i=0;i<count;i++)if(x>=faces[i].left&&x<=faces[i].right)
        intervals[n++]=(SupportInterval){faces[i].bottom,faces[i].top};
    qsort(intervals,(size_t)n,sizeof *intervals,cmp_support_interval);
    long double covered=-.5L;
    for(int i=0;i<n;i++) {
        if(intervals[i].lo>covered+tolerance)return 0;
        covered=fmaxl(covered,intervals[i].hi);
        if(covered>=.5L-tolerance)return 1;
    }
    return 0;
}
/* Use the same normalized coordinates and slab tests as the polygon union,
   but store only four bounds for exact rectangles. A coplanar oblique face
   requires the generic path, even if its angle is nearly a right angle. */
static OP_NOINLINE int support_rectangle_union(const OpPlacement *p,Shape a,const OpPlacement *placed,int count,double e) {
    SupportRectangle faces[OP_MAX_ITEMS];int nf=0,nx=2;
    SupportRectangle bounds={.5L,-.5L,.5L,-.5L};
    long double xs[OP_MAX_ITEMS*2+2];xs[0]=-.5L;xs[1]=.5L;
    for(int i=0;i<count;i++)if(fabs(p->z-placed[i].z-placed[i].height)<=e) {
        const OpPlacement *q=&placed[i];Shape b=shape(q);
        if(b.c!=0&&b.s!=0)return -1;
        /* Keep these operations identical to support_polygon's axis branch. */
        long double dx=(long double)q->x-p->x,dy=(long double)q->y-p->y;
        long double cx=dx*a.c+dy*a.s,cy=-dx*a.s+dy*a.c;
        long double hx=a.c==0?b.hy:b.hx,hy=a.c==0?b.hx:b.hy;
        long double left=fmaxl(-.5L,(cx-hx)/p->width),right=fminl(.5L,(cx+hx)/p->width);
        long double bottom=fmaxl(-.5L,(cy-hy)/p->length),top=fminl(.5L,(cy+hy)/p->length);
        if(left>right||bottom>top)continue;
        faces[nf++]=(SupportRectangle){left,right,bottom,top};
        if(left<bounds.left)bounds.left=left;
        if(right>bounds.right)bounds.right=right;
        if(bottom<bounds.bottom)bounds.bottom=bottom;
        if(top>bounds.top)bounds.top=top;
        xs[nx++]=left;xs[nx++]=right;
    }
    if(!nf)return 0;
    long double xtol=(long double)e/p->width,ytol=(long double)e/p->length;
    /* Reject only definite missing outer coverage. The X subtractions must
       match the first/last slabs exactly: gaps <= xtol are skipped. The Y
       comparisons match the initial and final section coverage tests.
       With xtol < 2*EPS and at most 2*OP_MAX_ITEMS+2 endpoints, at least one
       slab is tested. Bounds passing says nothing about interior holes.
       Wait until every coplanar face has been checked for oblique fallback. */
    if(bounds.left-(-.5L)>xtol||.5L-bounds.right>xtol||
       bounds.bottom>-.5L+ytol||bounds.top<.5L-ytol)return 0;
    qsort(xs,(size_t)nx,sizeof *xs,cmp_long_double);
    for(int i=1;i<nx;i++) {
        if(xs[i]-xs[i-1]<=xtol)continue;
        if(!support_rectangle_section(faces,nf,xs[i-1],ytol)||
           !support_rectangle_section(faces,nf,(xs[i-1]+xs[i])/2,ytol)||
           !support_rectangle_section(faces,nf,xs[i],ytol))return 0;
    }
    return 1;
}
static int support_union(const OpPlacement *p,Shape a,const OpPlacement *placed,int count,double e) {
    if(a.c==0||a.s==0) {
        int supported=support_rectangle_union(p,a,placed,count,e);
        if(supported>=0)return supported;
    }
    return support_polygon_union(p,a,placed,count,e);
}
int op_supported(const OpPlacement *p,const OpPlacement *placed,int count) {
    if(count<0||count>OP_MAX_ITEMS)return 0;
    double e=geometric_epsilon(p);
    if(fabs(p->z)<e)return 1;
    Shape a=shape(p);
    for(int i=0;i<count;i++) {
        const OpPlacement *b=&placed[i];
        if(fabs(p->z-b->z-b->height)>e)continue;
        Shape s=shape(b); int inside=1;
        if((a.c==0||a.s==0)&&(s.c==0||s.s==0)) {
            if(fabs(p->x-b->x)+a.hx<=s.hx+e&&fabs(p->y-b->y)+a.hy<=s.hy+e)return 1;
            continue;
        }
        for(int k=0;k<4;k++) {
            double dx=((k&1)?1:-1)*p->width/2,dy=((k&2)?1:-1)*p->length/2;
            double x=p->x+a.c*dx-a.s*dy-b->x,y=p->y+a.s*dx+a.c*dy-b->y;
            if(fabs(x*s.c+y*s.s)>b->width/2+e || fabs(-x*s.s+y*s.c)>b->length/2+e){inside=0;break;}
        }
        if(inside)return 1;
    }
    return support_union(p,a,placed,count,e);
}
/* Positive overlap with a coplanar top face, at least a 16-epsilon strip
   along the footprint perimeter so that edge or vertex contact never counts. */
int op_rests(const OpPlacement *p,const OpPlacement *placed,int count) {
    if(count<0||count>OP_MAX_ITEMS)return 0;
    double e=geometric_epsilon(p);
    if(fabs(p->z)<e)return 1;
    Shape a=shape(p);
    long double minimum=16.0L*e*((long double)p->width+p->length)/((long double)p->width*p->length);
    for(int i=0;i<count;i++) {
        const OpPlacement *q=&placed[i];
        if(fabs(p->z-q->z-q->height)>e)continue;
        SupportPoint poly[16];int n=support_polygon(p,a,q,poly);
        long double area=0;
        for(int k=0;k<n;k++){SupportPoint u=poly[k],v=poly[(k+1)%n];area+=u.x*v.y-v.x*u.y;}
        if(fabsl(area)/2>minimum)return 1;
    }
    return 0;
}
static int range(double x,double lo,double hi){return isfinite(x)&&x>=lo&&x<=hi;}
static int fail(char *e,int n,const char *msg){if(e&&n>0)snprintf(e,(size_t)n,"%s",msg);return 1;}
static int valid(const OpRequest *r,char *e,int n) {
    if(!r)return fail(e,n,"null request");
    if(r->item_count<0||r->item_count>OP_MAX_ITEMS||r->box_count<0||r->box_count>OP_MAX_BOXES)return fail(e,n,"item or box limit exceeded");
    const OpOptions *o=&r->options;
    if(!range(o->angle_step,1,90)||floor(o->angle_step)!=o->angle_step||!range(o->time_limit_ms,1,60000)||!range(o->gap,0,1e6)||o->restarts<1||o->restarts>64||o->max_candidates<1||o->max_candidates>100000000||
       (o->support!=OP_SUPPORT_FULL_BASE&&o->support!=OP_SUPPORT_CONTACT)||o->improve<0||o->improve>1)return fail(e,n,"invalid search options");
    for(int i=0;i<r->item_count;i++) {
        const OpItem *a=&r->items[i];
        if(!memchr(a->id,0,OP_ID_SIZE)||!a->id[0]||!range(a->width,1e-4,1e6)||!range(a->length,1e-4,1e6)||!range(a->height,1e-4,1e6)||!range(a->weight,0,1e12)||a->rotation<0||a->rotation>2||a->diagonal<0||a->diagonal>1||a->instance<0||a->instance>=OP_MAX_ITEMS)return fail(e,n,"invalid item");
        for(int j=0;j<i;j++)if(!strcmp(a->id,r->items[j].id)&&a->instance==r->items[j].instance)return fail(e,n,"duplicate item instance");
    }
    for(int i=0;i<r->box_count;i++) {
        const OpBox *a=&r->boxes[i];
        if(!memchr(a->id,0,OP_ID_SIZE)||!a->id[0]||!range(a->width,1e-4,1e6)||!range(a->length,1e-4,1e6)||!range(a->height,1e-4,1e6)||!range(a->max_weight,0,1e12)||!range(a->cost,0,1e12)||a->quantity< -1||a->quantity>OP_MAX_ITEMS)return fail(e,n,"invalid box");
        for(int j=0;j<i;j++)if(!strcmp(a->id,r->boxes[j].id))return fail(e,n,"duplicate box id");
    }
    return 0;
}
#define FILL_CACHE_SIZE 32
typedef struct {
    int box,run,diagonal,count;
    int order[OP_MAX_ITEMS];
    unsigned char used[OP_MAX_ITEMS];
    OpPlacement placements[OP_MAX_ITEMS];
    double weight;
} FillCache;
typedef struct {
    const OpRequest *r;double deadline;uint64_t candidates;unsigned rng;
    int timed_out,budget_exhausted,run,diagonal,has_diagonals;
    FillCache *cache;int cache_count,cache_next;
} Search;
static int stopped(Search *s) {
    if(s->timed_out||s->budget_exhausted)return 1;
    if(op_now_ms()>=s->deadline){s->timed_out=1;return 1;}
    if(s->candidates>=s->r->options.max_candidates){s->budget_exhausted=1;return 1;}
    return 0;
}
static unsigned random_u32(Search *s) { unsigned x=s->rng;x^=x<<13;x^=x>>17;x^=x<<5;return s->rng=x; }
static int cmp_double(const void *a,const void *b){double x=*(const double*)a,y=*(const double*)b;return (x>y)-(x<y);}
static void anchor(double *xs,int *n,double x,double lo,double hi) {
    if(x<lo-EPS||x>hi+EPS||*n>=ANCHORS)return;
    x=fmax(lo,fmin(hi,x));
    for(int i=0;i<*n;i++)if(fabs(xs[i]-x)<EPS)return;
    xs[(*n)++]=x;
}
static int axis_aligned(const OpPlacement *p) {
    return p->angle==0||p->angle==90||fabs(remainder(p->angle,90))<EPS;
}
/* Broad-phase sweep for exact axis-aligned footprints. At fixed Z and one
   horizontal coordinate a collision excludes an interval on the other; omit those grid points before
   spending a full candidate validation. Never apply this to oblique shapes. */
static int skip_blocked_coordinate(const OpPlacement *p,Shape sh,const OpPlacement *in,int count,
                          const double *positions,int n,int index,double gap,int axis) {
    if(!axis_aligned(p))return index;
    for(int k=0;k<count && index<n;k++) {
        const OpPlacement *q=&in[k];if(!axis_aligned(q))continue;
        double e=fmin(geometric_epsilon(p),geometric_epsilon(q));
        if(p->z+p->height<=q->z+e||q->z+q->height<=p->z+e)continue;
        Shape v=shape(q);
        double cross=axis?p->x-q->x:p->y-q->y,half=axis?sh.hx+v.hx:sh.hy+v.hy;
        if(fabs(cross)>=half+gap-e)continue;
        double center=axis?q->y:q->x,radius=axis?v.hy+sh.hy:v.hx+sh.hx;
        double left=center-radius-gap+e,right=center+radius+gap-e;
        if(positions[index]>left&&positions[index]<right) {
            do{index++;}while(index<n&&positions[index]<right);
            k=-1;
        }
    }
    return index;
}
typedef struct {
    long double left,right,bottom,top;
    double allowance;
    int enabled,count;
    SupportRectangle faces[OP_MAX_ITEMS];
} SupportBounds;
/* A support union cannot extend beyond the outer bounds of its coplanar
   faces. Build this necessary condition once per pose/Z, before traversing
   its XY grid. Oblique coplanar faces retain the generic validation path. */
static void support_bounds(const OpPlacement *p,Shape a,const OpPlacement *in,int count,SupportBounds *bounds) {
    bounds->enabled=bounds->count=0;bounds->allowance=0;
    bounds->left=bounds->bottom=LDBL_MAX;bounds->right=bounds->top=-LDBL_MAX;
    double e=geometric_epsilon(p),scale=fmax(1,fmax(p->width,p->length));
    if(fabs(p->z)<e||(a.c!=0&&a.s!=0))return;
    bounds->enabled=1;
    for(int k=0;k<count;k++) {
        const OpPlacement *q=&in[k];
        if(fabs(p->z-q->z-q->height)>e)continue;
        Shape b=shape(q);
        if(b.c!=0&&b.s!=0){bounds->enabled=0;return;}
        bounds->left=fminl(bounds->left,(long double)q->x-b.hx);
        bounds->right=fmaxl(bounds->right,(long double)q->x+b.hx);
        bounds->bottom=fminl(bounds->bottom,(long double)q->y-b.hy);
        bounds->top=fmaxl(bounds->top,(long double)q->y+b.hy);
        bounds->faces[bounds->count++]=(SupportRectangle){(long double)q->x-b.hx,(long double)q->x+b.hx,
                                                       (long double)q->y-b.hy,(long double)q->y+b.hy};
        scale=fmax(scale,fmax(fabs(q->x)+b.hx,fabs(q->y)+b.hy));
    }
    /* The validator allows e at outer edges. Keep additional roundoff room
       for its double single-face containment and normalized union arithmetic.
       These bounds only reject; passing still requires full support checks. */
    bounds->allowance=e+64*DBL_EPSILON*scale;
}
static void support_position_range(const double *positions,int *begin,int *end,double half,
                                   long double lo,long double hi,double allowance) {
    while(*begin<*end&&(long double)positions[*begin]-half<lo-allowance)(*begin)++;
    while(*end>*begin&&(long double)positions[*end-1]+half>hi+allowance)(*end)--;
}
/* Full support must reach both outer footprint edges. Reuse the coplanar
   faces to bound the inner coordinate once per row. The union validator can
   skip consecutive tiny local-X slabs: allow their entire possible span,
   on both axes, rather than assume a single e-sized gap. */
static void support_row_range(const OpPlacement *p,Shape a,const SupportBounds *bounds,int axis,
                              const double *positions,int *begin,int *end) {
    if(!bounds->enabled)return;
    double center=axis?p->x:p->y,half=axis?a.hx:a.hy,inner_half=axis?a.hy:a.hx;
    double allowance=bounds->allowance+64*DBL_EPSILON*fabs(center)+
                     (2*bounds->count+2)*geometric_epsilon(p);
    long double lo=-LDBL_MAX,hi=LDBL_MAX;
    for(int side=-1;side<=1;side+=2) {
        long double edge=(long double)center+side*half,left=LDBL_MAX,right=-LDBL_MAX;
        for(int k=0;k<bounds->count;k++) {
            const SupportRectangle *f=&bounds->faces[k];
            long double outer_lo=axis?f->left:f->bottom,outer_hi=axis?f->right:f->top;
            if(outer_lo>edge+allowance||outer_hi<edge-allowance)continue;
            left=fminl(left,axis?f->bottom:f->left);right=fmaxl(right,axis?f->top:f->right);
        }
        lo=fmaxl(lo,left);hi=fminl(hi,right);
    }
    support_position_range(positions,begin,end,inner_half,lo,hi,allowance);
}
static void contact_position_range(const double *positions,int *begin,int *end,double half,long double lo,long double hi) {
    while(*begin<*end&&(long double)positions[*begin]+half<=lo)(*begin)++;
    while(*end>*begin&&(long double)positions[*end-1]-half>=hi)(*end)--;
}
static int outside_support_bounds(const OpPlacement *p,Shape a,const SupportBounds *bounds) {
    if(!bounds->enabled)return 0;
    double allowance=bounds->allowance+64*DBL_EPSILON*fmax(fabs(p->x),fabs(p->y));
    return (long double)p->x-a.hx<bounds->left-allowance||
           (long double)p->x+a.hx>bounds->right+allowance||
           (long double)p->y-a.hy<bounds->bottom-allowance||
           (long double)p->y+a.hy>bounds->top+allowance;
}
static int resting(const Search *s,const OpPlacement *p,const OpPlacement *in,int count) {
    return s->r->options.support==OP_SUPPORT_FULL_BASE?op_supported(p,in,count):op_rests(p,in,count);
}
static int pose_better(const OpPlacement *p,const OpPlacement *best,int mode) {
    Shape a=shape(p),b=shape(best);
    /* Bottom-left/back across orientations, not first orientation that fits.
       Shelf direction, wall building and compactness diversify restarts. */
    double x[3],y[3];
    if(mode==4) {
        /* Wall building: fill the back wall to full height before advancing. */
        x[0]=p->x+a.hx;y[0]=best->x+b.hx;x[1]=p->z;y[1]=best->z;x[2]=p->y+a.hy;y[2]=best->y+b.hy;
        for(int k=0;k<3;k++){if(x[k]<y[k]-EPS)return 1;if(x[k]>y[k]+EPS)return 0;}
        return p->height<best->height-EPS;
    }
    x[0]=p->z+(mode==2?p->height:0);y[0]=best->z+(mode==2?best->height:0);
    x[1]=mode==1?p->x+a.hx:p->y+a.hy;y[1]=mode==1?best->x+b.hx:best->y+b.hy;
    if(mode==3){x[1]+=p->x+a.hx;y[1]+=best->x+b.hx;}
    x[2]=mode==1?p->y+a.hy:p->x+a.hx;y[2]=mode==1?best->y+b.hy:best->x+b.hx;
    for(int k=0;k<3;k++){if(x[k]<y[k]-EPS)return 1;if(x[k]>y[k]+EPS)return 0;}
    return p->height<best->height-EPS;
}
static int feasible(Search *s,const OpPlacement *p,const OpBox *box,const OpPlacement *in,int count) {
    if(stopped(s))return 0;
    s->candidates++;
    double gap=s->r->options.gap;
    if(!op_inside(p,box,gap)||!resting(s,p,in,count))return 0;
    for(int k=0;k<count;k++)if(op_intersects(p,&in[k],gap))return 0;
    return 1;
}
static void edge_contacts(Search *s,OpPlacement p,const OpBox *box,const OpPlacement *in,int count,
                          OpPlacement *out,int *found) {
    /* Each fill_box starts empty; place generates only 0/90 yaw in the
       orthogonal phase, so every pair would skip contact generation. Keep
       the first loop stop check for its final-candidate budget flag. */
    if(!s->diagonal){if(count>0)stopped(s);return;}
    Shape a=shape(&p);double gap=s->r->options.gap;
    for(int k=0;k<count && !stopped(s);k++) {
        const OpPlacement *q=&in[k];if(axis_aligned(&p)&&axis_aligned(q))continue;
        Shape b=shape(q);
        for(int axis=0;axis<2;axis++) {
            double nx=axis?-b.s:b.c,ny=axis?b.c:b.s,tx=-ny,ty=nx;
            double qr=(axis?q->length:q->width)/2,qt=(axis?q->width:q->length)/2;
            double pr=(fabs(nx*a.c+ny*a.s)*p.width+fabs(-nx*a.s+ny*a.c)*p.length)/2;
            double pt=(fabs(tx*a.c+ty*a.s)*p.width+fabs(-tx*a.s+ty*a.c)*p.length)/2;
            for(int side=-1;side<=1;side+=2)for(int align=-1;align<=1;align++) {
                if(align && fabs(qt-pt)<EPS)continue;
                p.x=q->x+side*(qr+pr+gap)*nx+align*(qt-pt)*tx;
                p.y=q->y+side*(qr+pr+gap)*ny+align*(qt-pt)*ty;
                p.z=q->z;
                if(stopped(s))return;
                if(feasible(s,&p,box,in,count)&&(!*found||pose_better(&p,out,s->run%4))) {*out=p;*found=1;}
            }
        }
    }
}
static int place(Search *s,int item,const OpBox *box,const OpPlacement *in,int count,OpPlacement *out) {
    const OpItem *a=&s->r->items[item];
    /* Three supporting faces cover all orthogonal axis assignments. Swapped
       faces add distinct sampled yaws if the angle step does not divide 90. */
    double d[6][3]={{a->width,a->length,a->height},{a->width,a->height,a->length},{a->length,a->height,a->width},
                    {a->length,a->width,a->height},{a->height,a->width,a->length},{a->height,a->length,a->width}};
    double gap=s->r->options.gap,angles[182];int na=0;
    angles[na++]=0;
    if(a->rotation!=OP_NONE) {
        angles[na++]=90;
        if(a->diagonal && s->diagonal)
            for(double t=s->r->options.angle_step;t<180;t+=s->r->options.angle_step)if(fabs(t-90)>EPS)angles[na++]=t;
    }
    int nf=a->rotation==OP_ANY?(na>2&&fmod(90,s->r->options.angle_step)!=0?6:3):1,found=0;
    double poses[6][3];int pose_count=0;
    for(int fi=0;fi<nf;fi++) {
        int f=(fi+(s->run>0?s->run/2:0))%nf;
        for(int ai=0;ai<na;ai++) {
            int ix=ai;
            if(ai>=2 && s->run%2)ix=na+1-ai;
            OpPlacement p={item,0,0,0,0,d[f][0],d[f][1],d[f][2],angles[ix]};
            /* Exact dimensions identify equivalent orthogonal footprints.
               Keep the first representation and its tie-breaking order.
               Sampled oblique yaws retain the complete original portfolio. */
            if(!s->diagonal) {
                double w=p.angle==90?p.length:p.width,l=p.angle==90?p.width:p.length;
                int duplicate=0;
                for(int k=0;k<pose_count;k++)if(poses[k][0]==w&&poses[k][1]==l&&poses[k][2]==p.height){duplicate=1;break;}
                if(duplicate)continue;
                poses[pose_count][0]=w;poses[pose_count][1]=l;poses[pose_count++][2]=p.height;
            }
            if(stopped(s))return found;
            Shape sh=shape(&p);
            if(2*sh.hx+2*gap>box->width+EPS||2*sh.hy+2*gap>box->length+EPS||p.height>box->height+EPS)continue;
            double xs[ANCHORS],ys[ANCHORS],zs[ANCHORS];int nx=0,ny=0,nz=0;
            double xmin=sh.hx+gap,xmax=box->width-sh.hx-gap,ymin=sh.hy+gap,ymax=box->length-sh.hy-gap;
            anchor(xs,&nx,xmin,xmin,xmax);anchor(xs,&nx,xmax,xmin,xmax);
            anchor(ys,&ny,ymin,ymin,ymax);anchor(ys,&ny,ymax,ymin,ymax);
            anchor(zs,&nz,0,0,box->height-p.height);
            for(int k=0;k<count;k++) {
                const OpPlacement *q=&in[k];Shape h=shape(q);
                anchor(xs,&nx,q->x-h.hx-sh.hx-gap,xmin,xmax);
                anchor(xs,&nx,q->x+h.hx+sh.hx+gap,xmin,xmax);
                anchor(xs,&nx,q->x-h.hx+sh.hx,xmin,xmax);
                anchor(xs,&nx,q->x+h.hx-sh.hx,xmin,xmax);
                anchor(xs,&nx,q->x,xmin,xmax);
                anchor(ys,&ny,q->y-h.hy-sh.hy-gap,ymin,ymax);
                anchor(ys,&ny,q->y+h.hy+sh.hy+gap,ymin,ymax);
                anchor(ys,&ny,q->y-h.hy+sh.hy,ymin,ymax);
                anchor(ys,&ny,q->y+h.hy-sh.hy,ymin,ymax);
                anchor(ys,&ny,q->y,ymin,ymax);
                anchor(zs,&nz,q->z+q->height,0,box->height-p.height);
            }
            qsort(xs,(size_t)nx,sizeof(double),cmp_double);qsort(ys,(size_t)ny,sizeof(double),cmp_double);qsort(zs,(size_t)nz,sizeof(double),cmp_double);
            /* Every other cycle of four restarts builds walls instead of
               preferring the lowest top. */
            int mode=s->run%4;if(mode==2&&!((s->run/4)%2))mode=4;
            int axis=mode==1||mode==4,grid_found=0;
            const double *inner=axis?ys:xs,*outer=axis?xs:ys;
            int ni=axis?ny:nx,no=axis?nx:ny;OpPlacement grid_best;
            /* Wall building compares the first feasible point of every level. */
            for(int zi=0;zi<nz&&!(grid_found&&mode!=4);zi++) {
            if(stopped(s))return found;
            p.z=zs[zi];SupportBounds bounds;support_bounds(&p,sh,in,count,&bounds);
            int outer_begin=0,outer_end=no,inner_begin=0,inner_end=ni;
            if(s->r->options.support!=OP_SUPPORT_FULL_BASE) {
                /* Contact needs overlap with a coplanar top face: the footprint
                   must reach into the faces' union bounds on both axes. */
                if(bounds.enabled) {
                    if(!bounds.count)continue;
                    contact_position_range(outer,&outer_begin,&outer_end,axis?sh.hx:sh.hy,
                                           axis?bounds.left:bounds.bottom,axis?bounds.right:bounds.top);
                    contact_position_range(inner,&inner_begin,&inner_end,axis?sh.hy:sh.hx,
                                           axis?bounds.bottom:bounds.left,axis?bounds.top:bounds.right);
                }
                bounds.enabled=0;
            }
            if(bounds.enabled) {
                double allowance=bounds.allowance+64*DBL_EPSILON*fmax(box->width,box->length);
                support_position_range(outer,&outer_begin,&outer_end,axis?sh.hx:sh.hy,
                                       axis?bounds.left:bounds.bottom,axis?bounds.right:bounds.top,allowance);
                support_position_range(inner,&inner_begin,&inner_end,axis?sh.hy:sh.hx,
                                       axis?bounds.bottom:bounds.left,axis?bounds.top:bounds.right,allowance);
            }
            for(int oi=outer_begin;oi<outer_end;oi++) {
                if(stopped(s))return found;
                if(mode==3&&grid_found&&outer[oi]+inner[0]>grid_best.x+grid_best.y+EPS)break;
                if(axis)p.x=outer[oi];else p.y=outer[oi];
                int begin=inner_begin,end=inner_end;
                support_row_range(&p,sh,&bounds,axis,inner,&begin,&end);
                for(int ii=begin;ii<end;ii++) {
                    if(stopped(s))return found;
                    p.z=zs[zi];if(axis)p.x=outer[oi];else p.y=outer[oi];
                    ii=skip_blocked_coordinate(&p,sh,in,count,inner,end,ii,gap,axis);if(ii==end)break;
                    if(axis)p.y=inner[ii];else p.x=inner[ii];
                    if(outside_support_bounds(&p,sh,&bounds))continue;
                    s->candidates++;
                    if(!op_inside(&p,box,gap)||!resting(s,&p,in,count))continue;
                    int ok=1;for(int k=0;k<count;k++)if(op_intersects(&p,&in[k],gap)){ok=0;break;}
                    if(ok) {
                        if(!found||pose_better(&p,out,mode))*out=p;
                        found=1;
                        if(!grid_found||pose_better(&p,&grid_best,mode))grid_best=p;
                        grid_found=1;
                        if(mode==4)goto next_level;
                        if(mode!=3)goto next_pose;
                        /* For the compact policy, compare the first feasible
                           point in each row until its lower bound cannot win. */
                        break;
                    }
                }
            }
            next_level:;
            }
            next_pose:
            edge_contacts(s,p,box,in,count,out,&found);
        }
    }
    return found;
}
static double item_volume(const OpItem *i){return i->width*i->length*i->height;}
static double box_volume(const OpBox *b){return b->width*b->length*b->height;}
static void summarize(const OpRequest *r,OpResult *o) {
    int used[OP_MAX_ITEMS]={0};double v=0,bv=0;o->total_cost=0;o->unpacked_count=0;
    for(int i=0;i<o->placement_count;i++){int k=o->placements[i].item_index;used[k]=1;v+=item_volume(&r->items[k]);}
    for(int i=0;i<r->item_count;i++)if(!used[i])o->unpacked[o->unpacked_count++]=i;
    for(int i=0;i<o->bin_count;i++){const OpBox *b=&r->boxes[o->bins[i].box_index];bv+=box_volume(b);o->total_cost+=b->cost;}
    o->utilization=bv?v/bv:0;
}
static int better(const OpRequest *r,const OpResult *a,const OpResult *b) {
    if(a->unpacked_count!=b->unpacked_count)return a->unpacked_count<b->unpacked_count;
    if(a->total_cost!=b->total_cost)return a->total_cost<b->total_cost;
    if(a->bin_count!=b->bin_count)return a->bin_count<b->bin_count;
    double av=0,bv=0;
    for(int i=0;i<a->bin_count;i++)av+=box_volume(&r->boxes[a->bins[i].box_index]);
    for(int i=0;i<b->bin_count;i++)bv+=box_volume(&r->boxes[b->bins[i].box_index]);
    return av<bv;
}
static double sort_key(const OpItem *a,int mode) {
    if(mode==4)return a->width+a->length+a->height;
    if(mode==5)return a->height;
    if(mode==1)return fmax(a->width,fmax(a->length,a->height));
    if(mode==2)return a->width*a->length;
    if(mode==3)return a->weight;
    return item_volume(a);
}
#define BOX_BEAM_WIDTH 4
typedef struct {
    OpResult result;
    unsigned char used[OP_MAX_ITEMS];
    int stock[OP_MAX_BOXES];
} BoxState;
static int fill_box(Search *s,int bi,const int *order,const unsigned char *used,OpPlacement *current,double *weight) {
    const OpRequest *r=s->r;const OpBox *b=&r->boxes[bi];int count=0;*weight=0;
    if(stopped(s))return 0;
    /* A closed box depends only on this key. Reuse completed trials, never
       interrupted prefixes; hits still obey the one global deadline/cap. */
    for(int k=0;k<s->cache_count;k++) {
        const FillCache *entry=&s->cache[k];
        if(entry->box==bi&&entry->run==s->run&&entry->diagonal==s->diagonal&&
           !memcmp(entry->used,used,(size_t)r->item_count)&&
           !memcmp(entry->order,order,(size_t)r->item_count*sizeof *order)) {
            memcpy(current,entry->placements,(size_t)entry->count*sizeof *current);
            *weight=entry->weight;return entry->count;
        }
    }
    for(int oi=0;oi<r->item_count&&!stopped(s);oi++) {
        int ii=order[oi];const OpItem *a=&r->items[ii];
        /* Relative rounding allowance grows with the number of additions;
           no fixed weight epsilon, and zero capacity remains strict. */
        double sum_weight=*weight+a->weight;
        double roundoff=2*DBL_EPSILON*(count+2)*fmax(sum_weight,b->max_weight);
        if(used[ii]||(sum_weight>b->max_weight&&(b->max_weight==0||sum_weight-b->max_weight>roundoff)))continue;
        if(place(s,ii,b,current,count,&current[count])){*weight+=a->weight;count++;}
    }
    if(s->cache&&!s->timed_out&&!s->budget_exhausted&&s->candidates<r->options.max_candidates&&op_now_ms()<s->deadline) {
        int slot=s->cache_next;s->cache_next=(slot+1)%FILL_CACHE_SIZE;
        if(s->cache_count<FILL_CACHE_SIZE)s->cache_count++;
        FillCache *entry=&s->cache[slot];
        entry->box=bi;entry->run=s->run;entry->diagonal=s->diagonal;entry->count=count;entry->weight=*weight;
        memcpy(entry->used,used,(size_t)r->item_count);
        memcpy(entry->order,order,(size_t)r->item_count*sizeof *order);
        memcpy(entry->placements,current,(size_t)count*sizeof *current);
    }
    return count;
}
static void append_bin(OpResult *result,int bi,const OpPlacement *current,int count,double weight) {
    int bin=result->bin_count++;result->bins[bin]=(OpBin){bi,weight};
    for(int k=0;k<count;k++) {
        OpPlacement p=current[k];p.bin_index=bin;
        result->placements[result->placement_count++]=p;
    }
}
/* Placement in closed bins cannot affect any later bin. Deduplicate states
   with the same remaining items and stock, regardless of their bin order. */
static int same_remaining(const OpRequest *r,const BoxState *a,const BoxState *b) {
    return !memcmp(a->used,b->used,(size_t)r->item_count)&&
        !memcmp(a->stock,b->stock,(size_t)r->box_count*sizeof *a->stock);
}
static void search_box_choices(Search *s,const int *order,OpResult *out,BoxState *states) {
    const OpRequest *r=s->r;BoxState *front=states,*next=states+BOX_BEAM_WIDTH;
    memset(front,0,sizeof *front);
    for(int bi=0;bi<r->box_count;bi++)front->stock[bi]=r->boxes[bi].quantity;
    int nfront=1;
    for(int depth=0;nfront&&depth<r->item_count&&!stopped(s);depth++) {
        int nnext=0;
        for(int k=0;k<nfront&&!stopped(s);k++)for(int bi=0;bi<r->box_count&&!stopped(s);bi++) {
            const BoxState *base=&front[k];if(base->stock[bi]==0)continue;
            if(!out->unpacked_count) {
                /* Completing this prefix in the next box is optimistic.
                   Further boxes have nonnegative cost and positive volume,
                   so they cannot improve this lexicographic lower bound. */
                double cost=base->result.total_cost+r->boxes[bi].cost;
                int bins=base->result.bin_count+1;
                if(cost>out->total_cost||(cost==out->total_cost&&bins>out->bin_count))continue;
                if(cost==out->total_cost&&bins==out->bin_count) {
                    double volume=0,incumbent_volume=0;
                    for(int j=0;j<base->result.bin_count;j++)volume+=box_volume(&r->boxes[base->result.bins[j].box_index]);
                    volume+=box_volume(&r->boxes[bi]);
                    for(int j=0;j<out->bin_count;j++)incumbent_volume+=box_volume(&r->boxes[out->bins[j].box_index]);
                    if(volume>=incumbent_volume)continue;
                }
            }
            OpPlacement current[OP_MAX_ITEMS];double weight;
            int count=fill_box(s,bi,order,base->used,current,&weight);if(!count)continue;
            BoxState candidate=*base;
            append_bin(&candidate.result,bi,current,count,weight);
            if(candidate.stock[bi]>0)candidate.stock[bi]--;
            for(int j=0;j<count;j++)candidate.used[current[j].item_index]=1;
            summarize(r,&candidate.result);
            /* Commit every validated prefix before ranking or budget checks. */
            if(better(r,&candidate.result,out))*out=candidate.result;
            if(!candidate.result.unpacked_count)continue;
            if(!out->unpacked_count&&(candidate.result.total_cost>out->total_cost||
               (candidate.result.total_cost==out->total_cost&&candidate.result.bin_count>=out->bin_count)))continue;
            int slot=-1;
            for(int j=0;j<nnext;j++)if(same_remaining(r,&candidate,&next[j])){slot=j;break;}
            if(slot>=0){if(better(r,&candidate.result,&next[slot].result))next[slot]=candidate;continue;}
            if(nnext<BOX_BEAM_WIDTH){next[nnext++]=candidate;continue;}
            int worst=0;
            for(int j=1;j<nnext;j++)if(better(r,&next[worst].result,&next[j].result))worst=j;
            if(better(r,&candidate.result,&next[worst].result))next[worst]=candidate;
        }
        BoxState *swap=front;front=next;next=swap;nfront=nnext;
    }
}
/* Rebuild a promising single-box alternative after the original portfolio.
   Move only missed items in the trial order, retaining every other item's
   relative order. A failed or interrupted rebuild never replaces an incumbent. */
/* Shrinking keeps each sorted order with its original pose policy: the area
   order of restart 2 tiles floors best with the lowest-top preference. */
static int refine_policy(int run){return run%4==2?run+4:run;}
static void refine_box_order(Search *s,int orders[64][OP_MAX_ITEMS],int runs,OpResult *out) {
    const OpRequest *r=s->r;
    if(out->unpacked_count||out->bin_count!=1)return;
    double volume=0,weight_sum=0;
    for(int i=0;i<r->item_count;i++){volume+=item_volume(&r->items[i]);weight_sum+=r->items[i].weight;}
    int attempts=0;
    for(int bi=0;bi<r->box_count&&attempts<40;bi++) {
        const OpBox *b=&r->boxes[bi],*old=&r->boxes[out->bins[0].box_index];
        double weight_error=2*DBL_EPSILON*(r->item_count+2)*fmax(weight_sum,b->max_weight);
        double volume_error=2*DBL_EPSILON*(r->item_count+2)*fmax(volume,box_volume(b));
        if(!b->quantity||b->cost>old->cost||(b->cost==old->cost&&box_volume(b)>=box_volume(old))||
           volume-box_volume(b)>volume_error||
           (weight_sum>b->max_weight&&(b->max_weight==0||weight_sum-b->max_weight>weight_error)))continue;
        if(stopped(s))break;
        int best_order[OP_MAX_ITEMS],best_count=-1,best_run=0;
        OpPlacement best[OP_MAX_ITEMS];unsigned char used[OP_MAX_ITEMS]={0};double weight;
        for(int run=0;run<runs&&!stopped(s)&&attempts<40;run++) {
            s->run=refine_policy(run);OpPlacement current[OP_MAX_ITEMS];
            int count=fill_box(s,bi,orders[run],used,current,&weight);attempts++;
            if(count>best_count){best_count=count;best_run=run;memcpy(best,current,(size_t)count*sizeof *best);memcpy(best_order,orders[run],(size_t)r->item_count*sizeof *best_order);}
            if(count==r->item_count){OpResult trial={0};append_bin(&trial,bi,current,count,weight);summarize(r,&trial);if(better(r,&trial,out))*out=trial;break;}
        }
        for(int iteration=0;iteration<3&&best_count<r->item_count&&!stopped(s);iteration++) {
            unsigned char placed[OP_MAX_ITEMS]={0};for(int i=0;i<best_count;i++)placed[best[i].item_index]=1;
            int base[OP_MAX_ITEMS];memcpy(base,best_order,(size_t)r->item_count*sizeof *base);int improved=0;
            for(int oi=0;oi<r->item_count&&best_count<r->item_count&&!stopped(s)&&attempts<40;oi++)if(!placed[base[oi]]) {
                for(int pos=0;pos<oi&&pos<8&&!stopped(s)&&attempts<40;pos++) {
                    int order[OP_MAX_ITEMS];memcpy(order,base,(size_t)r->item_count*sizeof *order);
                    int v=order[oi];memmove(order+pos+1,order+pos,(size_t)(oi-pos)*sizeof *order);order[pos]=v;
                    s->run=iteration?refine_policy(best_run):0;OpPlacement current[OP_MAX_ITEMS];
                    int count=fill_box(s,bi,order,used,current,&weight);attempts++;
                    if(count>best_count){best_count=count;memcpy(best,current,(size_t)count*sizeof *best);memcpy(best_order,order,(size_t)r->item_count*sizeof *best_order);improved=1;}
                    if(count==r->item_count){OpResult trial={0};append_bin(&trial,bi,current,count,weight);summarize(r,&trial);if(better(r,&trial,out))*out=trial;break;}
                }
            }
            if(!improved&&iteration>0)break;
        }
    }
}
/* Preserve the supported remainder of a smaller-box trial, remove one or two
   placements, then insert missed items before reinserting those removed.
   Removing a support face is permitted only if its entire remainder remains
   supported. The final complete candidate must beat the incumbent. */
static void reinsert_box_items(Search *s,int orders[64][OP_MAX_ITEMS],int runs,OpResult *out) {
    const OpRequest *r=s->r;if(out->unpacked_count||out->bin_count!=1)return;
    int attempts=0;
    for(int bi=0;bi<r->box_count&&attempts<40;bi++) {
        const OpBox *b=&r->boxes[bi],*old=&r->boxes[out->bins[0].box_index];
        if(!b->quantity||b->cost>old->cost||(b->cost==old->cost&&box_volume(b)>=box_volume(old)))continue;
        double volume=0,total_weight=0;
        for(int i=0;i<r->item_count;i++){volume+=item_volume(&r->items[i]);total_weight+=r->items[i].weight;}
        double volume_error=2*DBL_EPSILON*(r->item_count+2)*fmax(volume,box_volume(b));
        double weight_error=2*DBL_EPSILON*(r->item_count+2)*fmax(total_weight,b->max_weight);
        if(volume-box_volume(b)>volume_error||
           (total_weight>b->max_weight&&(b->max_weight==0||total_weight-b->max_weight>weight_error)))continue;
        if(stopped(s))break;
        int best_count=-1,best_run=0;OpPlacement best[OP_MAX_ITEMS];
        unsigned char used[OP_MAX_ITEMS]={0};double weight;
        for(int run=0;run<runs&&!stopped(s);run++) {
            OpPlacement current[OP_MAX_ITEMS];s->run=run;
            int count=fill_box(s,bi,orders[run],used,current,&weight);
            if(count>best_count){best_count=count;best_run=run;memcpy(best,current,(size_t)count*sizeof *best);}
            if(count==r->item_count){OpResult trial={0};append_bin(&trial,bi,current,count,weight);summarize(r,&trial);if(better(r,&trial,out))*out=trial;break;}
        }
        if(best_count==r->item_count)continue;
        s->run=best_run;int complete=0;
        for(int first=0;first<best_count&&!complete&&!stopped(s)&&attempts<40;first++)
            for(int second=-1;second<first&&!stopped(s)&&attempts<40;second++) {
            OpPlacement current[OP_MAX_ITEMS];int count=0;double sum=0;
            unsigned char placed[OP_MAX_ITEMS]={0},original[OP_MAX_ITEMS]={0};
            for(int k=0;k<best_count;k++) {
                original[best[k].item_index]=1;
                if(k!=first&&k!=second){current[count++]=best[k];placed[best[k].item_index]=1;sum+=r->items[best[k].item_index].weight;}
            }
            int supported=1;
            for(int k=0;k<count;k++)if(!resting(s,&current[k],current,count)){supported=0;break;}
            if(!supported)continue;
            attempts++;
            for(int removed=0;removed<2&&!stopped(s);removed++)
                for(int i=0;i<r->item_count&&!stopped(s);i++) {
                int ii=orders[best_run][i];if(placed[ii]||original[ii]!=removed)continue;
                double next=sum+r->items[ii].weight;
                double allowance=2*DBL_EPSILON*(count+2)*fmax(next,b->max_weight);
                if(next>b->max_weight&&(b->max_weight==0||next-b->max_weight>allowance))continue;
                if(place(s,ii,b,current,count,&current[count])){sum=next;placed[ii]=1;count++;}
            }
            if(count==r->item_count){OpResult trial={0};append_bin(&trial,bi,current,count,sum);summarize(r,&trial);if(better(r,&trial,out))*out=trial;complete=1;break;}
        }
    }
}
/* Lower bounds valid for every complete solution: total volume and weight
   against the largest available boxes, and products too large to share a box. */
static int count_bound(const OpRequest *r,double total,int volume) {
    double capacity[OP_MAX_BOXES];int stock[OP_MAX_BOXES],n=0;
    for(int i=0;i<r->box_count;i++)if(r->boxes[i].quantity) {
        capacity[n]=volume?box_volume(&r->boxes[i]):r->boxes[i].max_weight;stock[n++]=r->boxes[i].quantity;
    }
    for(int i=1;i<n;i++)for(int j=i;j>0&&capacity[j]>capacity[j-1];j--) {
        double c=capacity[j];capacity[j]=capacity[j-1];capacity[j-1]=c;int q=stock[j];stock[j]=stock[j-1];stock[j-1]=q;
    }
    double allowance=4*DBL_EPSILON*(r->item_count+2)*total,covered=0;int count=0;
    for(int i=0;i<n&&covered<total-allowance;i++) {
        if(capacity[i]<=0)break;
        if(stock[i]<0)return count+(int)ceil((total-allowance-covered)/capacity[i]);
        for(int k=0;k<stock[i]&&covered<total-allowance;k++){covered+=capacity[i];count++;}
    }
    return covered>=total-allowance?count:OP_MAX_ITEMS+1;
}
static int lower_bound(const OpRequest *r) {
    if(!r->item_count)return 0;
    double volume=0,weight=0,largest=0,heaviest=0;
    for(int i=0;i<r->box_count;i++)if(r->boxes[i].quantity) {
        largest=fmax(largest,box_volume(&r->boxes[i]));heaviest=fmax(heaviest,r->boxes[i].max_weight);
    }
    int big_volume=0,big_weight=0,bound=1,k;
    for(int i=0;i<r->item_count;i++) {
        double v=item_volume(&r->items[i]);volume+=v;weight+=r->items[i].weight;
        if(v>largest/2*(1+4*DBL_EPSILON))big_volume++;
        if(r->items[i].weight>heaviest/2*(1+4*DBL_EPSILON))big_weight++;
    }
    if((k=count_bound(r,volume,1))>bound)bound=k;
    if((k=count_bound(r,weight,0))>bound)bound=k;
    if(big_volume>bound)bound=big_volume;
    if(big_weight>bound)bound=big_weight;
    return bound;
}
/* Count and cost cannot improve. Cost is bounded only when all available
   box types share one cost; otherwise optimality is never claimed. */
static int bound_reached(const OpRequest *r,const OpResult *o,int bound) {
    if(o->unpacked_count||o->bin_count>bound)return 0;
    double cost=-1;
    for(int i=0;i<r->box_count;i++)if(r->boxes[i].quantity) {
        if(cost<0)cost=r->boxes[i].cost;else if(r->boxes[i].cost!=cost)return 0;
    }
    return 1;
}
/* A single box that no smaller-volume admissible box type could replace. */
static int volume_optimal(const OpRequest *r,const OpResult *o) {
    if(o->bin_count!=1)return 0;
    double volume=0,weight=0,smallest=DBL_MAX,slack=1-4*DBL_EPSILON*(r->item_count+2);
    for(int i=0;i<r->item_count;i++){volume+=item_volume(&r->items[i]);weight+=r->items[i].weight;}
    for(int i=0;i<r->box_count;i++) {
        const OpBox *b=&r->boxes[i];
        if(b->quantity&&box_volume(b)>=volume*slack&&b->max_weight>=weight*slack)smallest=fmin(smallest,box_volume(b));
    }
    return box_volume(&r->boxes[o->bins[0].box_index])<=smallest;
}
static int weight_allows(const OpBox *b,double current,double added,int count) {
    double sum=current+added,roundoff=2*DBL_EPSILON*(count+2)*fmax(sum,b->max_weight);
    return !(sum>b->max_weight&&(b->max_weight==0||sum-b->max_weight>roundoff));
}
static void greedy(Search *s,const int *order,OpResult *trial,OpResult *alternative,OpResult *out) {
    const OpRequest *r=s->r;int stock[OP_MAX_BOXES];unsigned char used[OP_MAX_ITEMS]={0};
    memset(trial,0,sizeof *trial);
    for(int i=0;i<r->box_count;i++)stock[i]=r->boxes[i].quantity;
    while(trial->placement_count<r->item_count&&!stopped(s)) {
        OpPlacement chosen[OP_MAX_ITEMS];int chosen_count=0,best_type=-1;
        double best_ratio=-1,chosen_weight=0,best_volume=0,best_cost=0;
        for(int bi=0;bi<r->box_count&&!stopped(s);bi++) {
            if(stock[bi]==0)continue;
            const OpBox *b=&r->boxes[bi];OpPlacement current[OP_MAX_ITEMS];double weight;
            int count=fill_box(s,bi,order,used,current,&weight);
            if(!count)continue;
            /* Retain every feasible trial, even if the greedy continuation chooses
               another box or the budget expires before this trial is committed. */
            *alternative=*trial;
            append_bin(alternative,bi,current,count,weight);
            summarize(r,alternative);if(better(r,alternative,out))*out=*alternative;
            double ratio=count/fmax(b->cost,1e-9),vol=box_volume(b);
            /* A count-only continuation can choose a larger first box even
               when two smaller boxes have the same cost and less volume.
               Keep that fast policy and also explore count density. */
            if(s->run%4==1)ratio/=vol;
            if(best_type<0||ratio>best_ratio|| (ratio==best_ratio&&(b->cost<best_cost||(b->cost==best_cost&&vol<best_volume)))) {
                memcpy(chosen,current,(size_t)count*sizeof *current);chosen_count=count;best_type=bi;best_ratio=ratio;chosen_weight=weight;best_volume=vol;best_cost=b->cost;
            }
        }
        if(best_type<0)break;
        int bin=trial->bin_count++;trial->bins[bin]=(OpBin){best_type,chosen_weight};
        if(stock[best_type]>0)stock[best_type]--;
        for(int k=0;k<chosen_count;k++){chosen[k].bin_index=bin;trial->placements[trial->placement_count++]=chosen[k];used[chosen[k].item_index]=1;}
        summarize(r,trial);if(better(r,trial,out))*out=*trial;
    }
}
/* Compact per-bin view of a result: placements grouped by bin, contiguous
   per bin as place() requires, with start offsets. */
typedef struct {
    int bins,box[OP_MAX_ITEMS],start[OP_MAX_ITEMS+1];
    double weight[OP_MAX_ITEMS],fill[OP_MAX_ITEMS];
    OpPlacement placed[OP_MAX_ITEMS];
} BinView;
static int view_count(const BinView *v,int b){return v->start[b+1]-v->start[b];}
static OpPlacement *view_items(BinView *v,int b){return &v->placed[v->start[b]];}
static void view_insert(const OpRequest *r,BinView *v,int b,OpPlacement p) {
    int at=v->start[b+1];
    memmove(&v->placed[at+1],&v->placed[at],(size_t)(v->start[v->bins]-at)*sizeof *v->placed);
    p.bin_index=b;v->placed[at]=p;
    for(int c=b+1;c<=v->bins;c++)v->start[c]++;
    v->weight[b]+=r->items[p.item_index].weight;v->fill[b]+=item_volume(&r->items[p.item_index]);
}
static void view_clear(BinView *v,int b) {
    int n=view_count(v,b),at=v->start[b];
    memmove(&v->placed[at],&v->placed[at+n],(size_t)(v->start[v->bins]-at-n)*sizeof *v->placed);
    for(int c=b+1;c<=v->bins;c++)v->start[c]-=n;
    v->weight[b]=v->fill[b]=0;
}
static void view_from(const OpRequest *r,const OpResult *o,BinView *v) {
    v->bins=o->bin_count;
    for(int b=0;b<=o->bin_count;b++)v->start[b]=0;
    for(int b=0;b<o->bin_count;b++){v->box[b]=o->bins[b].box_index;v->weight[b]=v->fill[b]=0;}
    for(int b=0;b<o->bin_count;b++)
        for(int i=0;i<o->placement_count;i++)if(o->placements[i].bin_index==b)view_insert(r,v,b,o->placements[i]);
}
static void result_from(const OpRequest *r,BinView *v,OpResult *o) {
    memset(o,0,sizeof *o);
    for(int b=0;b<v->bins;b++)if(view_count(v,b))append_bin(o,v->box[b],view_items(v,b),view_count(v,b),v->weight[b]);
    summarize(r,o);
}
static int stock_left(const OpRequest *r,const BinView *v,int bi,int ignore_a,int ignore_b) {
    if(r->boxes[bi].quantity<0)return 1;
    int used=0;for(int b=0;b<v->bins;b++)if(b!=ignore_a&&b!=ignore_b&&view_count(v,b)&&v->box[b]==bi)used++;
    return used<r->boxes[bi].quantity;
}
/* Move every product of one bin into the other bins, fullest bins first so
   emptier ones stay available. Products go in descending volume. */
static int empty_bin(Search *s,BinView *v,int target) {
    const OpRequest *r=s->r;int items[OP_MAX_ITEMS],n=view_count(v,target),rank[OP_MAX_ITEMS],nr=0;
    for(int k=0;k<n;k++)items[k]=view_items(v,target)[k].item_index;
    for(int i=1;i<n;i++){int x=items[i],j=i-1;while(j>=0&&item_volume(&r->items[items[j]])<item_volume(&r->items[x])){items[j+1]=items[j];j--;}items[j+1]=x;}
    view_clear(v,target);
    for(int b=0;b<v->bins;b++)if(b!=target&&view_count(v,b))rank[nr++]=b;
    for(int i=1;i<nr;i++){int x=rank[i],j=i-1;while(j>=0&&v->fill[rank[j]]<v->fill[x]){rank[j+1]=rank[j];j--;}rank[j+1]=x;}
    for(int k=0;k<n;k++) {
        int item=items[k],placed=0;
        for(int c=0;c<nr&&!placed;c++) {
            if(stopped(s))return 0;
            int b=rank[c];const OpBox *box=&r->boxes[v->box[b]];OpPlacement p;
            if(!weight_allows(box,v->weight[b],r->items[item].weight,view_count(v,b)))continue;
            if(place(s,item,box,view_items(v,b),view_count(v,b),&p)){view_insert(r,v,b,p);placed=1;}
        }
        if(!placed)return 0;
    }
    return 1;
}
/* Refill one or two bins from scratch into a single box of any admissible type. */
static int repack_bins(Search *s,int orders[64][OP_MAX_ITEMS],int runs,BinView *v,int a,int b) {
    const OpRequest *r=s->r;unsigned char used[OP_MAX_ITEMS];
    int needed=view_count(v,a)+(b>=0?view_count(v,b):0);
    double current_volume=box_volume(&r->boxes[v->box[a]])+(b>=0?box_volume(&r->boxes[v->box[b]]):0);
    double current_cost=r->boxes[v->box[a]].cost+(b>=0?r->boxes[v->box[b]].cost:0);
    memset(used,1,(size_t)r->item_count);
    for(int k=0;k<view_count(v,a);k++)used[view_items(v,a)[k].item_index]=0;
    if(b>=0)for(int k=0;k<view_count(v,b);k++)used[view_items(v,b)[k].item_index]=0;
    double volume=0,weight=0;
    for(int i=0;i<r->item_count;i++)if(!used[i]){volume+=item_volume(&r->items[i]);weight+=r->items[i].weight;}
    for(int bi=0;bi<r->box_count&&!stopped(s);bi++) {
        const OpBox *box=&r->boxes[bi];
        if(box->cost>current_cost||(box->cost==current_cost&&b<0&&box_volume(box)>=current_volume))continue;
        if(box_volume(box)<volume*(1-4*DBL_EPSILON*(needed+2))||!weight_allows(box,0,weight,needed))continue;
        if(!stock_left(r,v,bi,a,b))continue;
        for(int run=0;run<runs&&!stopped(s);run++) {
            OpPlacement current[OP_MAX_ITEMS];double w;s->run=run;
            int count=fill_box(s,bi,orders[run],used,current,&w);
            if(count!=needed)continue;
            view_clear(v,a);if(b>=0)view_clear(v,b);
            v->box[a]=bi;
            for(int k=0;k<count;k++)view_insert(r,v,a,current[k]);
            return 1;
        }
    }
    return 0;
}
/* Insert unpacked products, empty the least-filled bins, merge bin pairs and
   shrink single bins. Only an improvement on the incumbent is committed. */
/* Ruin and recreate inside one box. Remove a cluster of neighbouring products
   (plus any product left without rest), then reinsert the pending products,
   largest first with small random swaps. Keep the state with the least pending
   volume. Succeeds only if every original product stays and more of `extra`
   fit: all of it when need_all is set. */
typedef struct { OpPlacement p[OP_MAX_ITEMS];int count,pending[OP_MAX_ITEMS],npending;double weight,pending_volume; } DenseState;
static void dense_insert(Search *s,const OpBox *box,DenseState *d) {
    const OpRequest *r=s->r;
    for(int i=1;i<d->npending;i++){int x=d->pending[i],j=i-1;while(j>=0&&item_volume(&r->items[d->pending[j]])<item_volume(&r->items[x])){d->pending[j+1]=d->pending[j];j--;}d->pending[j+1]=x;}
    for(int k=0;k+1<d->npending;k++)if(random_u32(s)%4==0){int t=d->pending[k];d->pending[k]=d->pending[k+1];d->pending[k+1]=t;}
    int left=0;
    for(int k=0;k<d->npending;k++) {
        int item=d->pending[k];OpPlacement p;
        if(stopped(s)||!weight_allows(box,d->weight,r->items[item].weight,d->count)||!place(s,item,box,d->p,d->count,&p)){d->pending[left++]=item;continue;}
        d->p[d->count++]=p;d->weight+=r->items[item].weight;d->pending_volume-=item_volume(&r->items[item]);
    }
    d->npending=left;
}
static int densify(Search *s,BinView *v,int b,const int *extra,int nextra,int need_all,double ms) {
    const OpRequest *r=s->r;const OpBox *box=&r->boxes[v->box[b]];
    DenseState *best=malloc(sizeof *best),*work=malloc(sizeof *work);
    if(!best||!work){free(best);free(work);return 0;}
    unsigned char original[OP_MAX_ITEMS]={0};
    best->count=view_count(v,b);memcpy(best->p,view_items(v,b),(size_t)best->count*sizeof *best->p);
    best->weight=v->weight[b];best->npending=nextra;best->pending_volume=0;
    for(int k=0;k<best->count;k++)original[best->p[k].item_index]=1;
    for(int k=0;k<nextra;k++){best->pending[k]=extra[k];best->pending_volume+=item_volume(&r->items[extra[k]]);}
    double end=fmin(s->deadline,op_now_ms()+ms);int saved_run=s->run;
    dense_insert(s,box,best);
    while(best->npending&&!stopped(s)&&op_now_ms()<end&&best->count) {
        *work=*best;
        int seed=(int)(random_u32(s)%(unsigned)work->count),k=1+(int)(random_u32(s)%(unsigned)(work->count/10+2));
        double cx=work->p[seed].x,cy=work->p[seed].y,cz=work->p[seed].z,dist[OP_MAX_ITEMS];int idx[OP_MAX_ITEMS];
        for(int i=0;i<work->count;i++){idx[i]=i;dist[i]=fabs(work->p[i].x-cx)+fabs(work->p[i].y-cy)+fabs(work->p[i].z-cz);}
        for(int i=1;i<work->count;i++){int x=idx[i],j=i-1;while(j>=0&&dist[idx[j]]>dist[x]){idx[j+1]=idx[j];j--;}idx[j+1]=x;}
        unsigned char removed[OP_MAX_ITEMS]={0};
        for(int i=0;i<k&&i<work->count;i++)removed[idx[i]]=1;
        for(int changed=1;changed;) {
            /* Products resting on a removed one must leave too. */
            changed=0;OpPlacement kept[OP_MAX_ITEMS];int nk=0;
            for(int i=0;i<work->count;i++)if(!removed[i])kept[nk++]=work->p[i];
            for(int i=0;i<work->count;i++)if(!removed[i]&&work->p[i].z>0&&!resting(s,&work->p[i],kept,nk)){removed[i]=1;changed=1;}
        }
        int nk=0;
        for(int i=0;i<work->count;i++) {
            if(!removed[i]){work->p[nk++]=work->p[i];continue;}
            int item=work->p[i].item_index;work->pending[work->npending++]=item;
            work->weight-=r->items[item].weight;work->pending_volume+=item_volume(&r->items[item]);
        }
        work->count=nk;s->run=(int)(random_u32(s)%4);
        dense_insert(s,box,work);
        if(work->pending_volume<best->pending_volume-EPS||(work->pending_volume<=best->pending_volume+EPS&&random_u32(s)%2))*best=*work;
    }
    s->run=saved_run;
    int ok=1,extras_left=0,originals_left=0;
    for(int k=0;k<best->npending;k++){if(original[best->pending[k]])originals_left++;else extras_left++;}
    ok=ok&&!originals_left&&(need_all?extras_left==0:extras_left<nextra);
    if(ok){view_clear(v,b);for(int k=0;k<best->count;k++)view_insert(r,v,b,best->p[k]);}
    free(best);free(work);return ok;
}
static void improve_bins(Search *s,int orders[64][OP_MAX_ITEMS],int runs,OpResult *out) {
    const OpRequest *r=s->r;
    BinView *v=malloc(sizeof *v),*copy=malloc(sizeof *copy);OpResult *trial=malloc(sizeof *trial);
    if(!v||!copy||!trial){free(v);free(copy);free(trial);return;}
    int saved_run=s->run,saved_diagonal=s->diagonal;s->diagonal=s->has_diagonals;
    for(int round=0;round<8&&!stopped(s);round++) {
        int improved=0;view_from(r,out,v);
        for(int u=0;u<out->unpacked_count&&!stopped(s);u++) {
            int item=out->unpacked[u];
            for(int b=0;b<v->bins&&!stopped(s);b++) {
                const OpBox *box=&r->boxes[v->box[b]];OpPlacement p;
                if(!weight_allows(box,v->weight[b],r->items[item].weight,view_count(v,b)))continue;
                if(place(s,item,box,view_items(v,b),view_count(v,b),&p)){view_insert(r,v,b,p);break;}
            }
        }
        result_from(r,v,trial);
        if(better(r,trial,out)){*out=*trial;view_from(r,out,v);}
        if(r->options.improve&&out->unpacked_count&&!stopped(s)) {
            /* Leftovers: compact the roomiest bins around them. */
            for(int b=0;b<v->bins&&out->unpacked_count&&!stopped(s);b++) {
                double slice=fmax(20,(s->deadline-op_now_ms())/2);
                if(densify(s,v,b,out->unpacked,out->unpacked_count,0,slice)){result_from(r,v,trial);if(better(r,trial,out)){*out=*trial;improved=1;}view_from(r,out,v);}
            }
        }
        int order[OP_MAX_ITEMS];
        for(int b=0;b<v->bins;b++)order[b]=b;
        for(int i=1;i<v->bins;i++){int x=order[i],j=i-1;while(j>=0&&v->fill[order[j]]>v->fill[x]){order[j+1]=order[j];j--;}order[j+1]=x;}
        for(int k=0;k<v->bins&&v->bins>1&&!improved&&!stopped(s);k++)for(int policy=0;policy<4&&!improved&&!stopped(s);policy++) {
            s->run=policy;*copy=*v;
            if(empty_bin(s,copy,order[k])){result_from(r,copy,trial);if(better(r,trial,out)){*out=*trial;improved=1;}}
        }
        if(r->options.improve&&v->bins>1&&!improved&&!stopped(s)) {
            /* Empty the least-filled bin into another one by compacting it. */
            int target=order[0],extra[OP_MAX_ITEMS],n=view_count(v,target);
            for(int k=0;k<n;k++)extra[k]=view_items(v,target)[k].item_index;
            /* Spread them over the roomiest bins first; all must find a place. */
            *copy=*v;view_clear(copy,target);
            for(int k=1;k<v->bins&&n&&!stopped(s);k++) {
                double slice=fmax(20,(s->deadline-op_now_ms())/(2*(v->bins-k)));
                if(!densify(s,copy,order[k],extra,n,0,slice))continue;
                unsigned char placed[OP_MAX_ITEMS]={0};int left=0;
                for(int i=0;i<view_count(copy,order[k]);i++)placed[view_items(copy,order[k])[i].item_index]=1;
                for(int i=0;i<n;i++)if(!placed[extra[i]])extra[left++]=extra[i];
                n=left;
            }
            if(!n){result_from(r,copy,trial);if(better(r,trial,out)){*out=*trial;improved=1;}}
        }
        /* Merge and shrink only among the least-filled bins to bound the cost. */
        for(int i=0;i<v->bins&&i<6&&!improved&&!stopped(s);i++)for(int j=-1;j<i&&!improved&&!stopped(s);j++) {
            *copy=*v;
            if(repack_bins(s,orders,runs,copy,order[i],j<0?-1:order[j])){result_from(r,copy,trial);if(better(r,trial,out)){*out=*trial;improved=1;}}
        }
        if(!improved)break;
    }
    s->run=saved_run;s->diagonal=saved_diagonal;free(v);free(copy);free(trial);
}
/* Swap or move a few positions; a negative strength shuffles completely. */
static void perturb(Search *s,const int *base,int *order,int n,int strength) {
    memcpy(order,base,(size_t)n*sizeof *order);
    if(n<2)return;
    if(strength<0){for(int i=n-1;i>0;i--){int j=(int)(random_u32(s)%(unsigned)(i+1));int v=order[i];order[i]=order[j];order[j]=v;}return;}
    for(int k=0;k<strength;k++) {
        int i=(int)(random_u32(s)%(unsigned)n),j=(int)(random_u32(s)%(unsigned)n),v=order[i];
        if(random_u32(s)%2){order[i]=order[j];order[j]=v;}
        else if(i<j){memmove(order+i,order+i+1,(size_t)(j-i)*sizeof *order);order[j]=v;}
        else if(i>j){memmove(order+j+1,order+j,(size_t)(i-j)*sizeof *order);order[j]=v;}
    }
}
int op_pack(const OpRequest *r,OpResult *out,char *error,int error_size) {
    if(!out)return fail(error,error_size,"null result");
    memset(out,0,sizeof *out);if(valid(r,error,error_size))return 1;
    double start=op_now_ms();
    Search s={0};s.r=r;s.deadline=start+r->options.time_limit_ms;s.rng=r->options.seed?r->options.seed:0x6d2b79f5;
    summarize(r,out);OpResult *trial=calloc(1,sizeof *trial),*alternative=calloc(1,sizeof *alternative);
    if(!trial||!alternative){free(trial);free(alternative);return fail(error,error_size,"out of memory");}
    s.cache=calloc(FILL_CACHE_SIZE,sizeof *s.cache);
    int runs=0,orders[64][OP_MAX_ITEMS],has_diagonals=0,capacity_limited=0,bound=lower_bound(r);
    double all_weight=0,min_capacity=DBL_MAX;
    for(int i=0;i<r->item_count;i++)all_weight+=r->items[i].weight;
    for(int i=0;i<r->box_count;i++) {
        if(r->boxes[i].quantity>=0)capacity_limited=1;
        if(r->boxes[i].max_weight>0)min_capacity=fmin(min_capacity,r->boxes[i].max_weight);
    }
    if(all_weight>min_capacity)capacity_limited=1;
    for(int i=0;i<r->item_count;i++)if(r->items[i].diagonal&&r->items[i].rotation!=OP_NONE)has_diagonals=1;
    s.has_diagonals=has_diagonals;
    /* A single box at the count bound that no smaller box could replace is
       optimal for the whole objective: later phases cannot improve it. */
#define OPTIMAL() (bound_reached(r,out,bound)&&volume_optimal(r,out))
    /* Finish the exact same orthogonal portfolio first. Oblique permission
       can then improve the incumbent using only the remaining global budget.
       Item orders are reused, not regenerated or counted twice. */
    for(s.diagonal=0;s.diagonal<=has_diagonals&&!stopped(&s)&&!OPTIMAL();s.diagonal++) {
    int run_limit=s.diagonal?runs:r->options.restarts;
    for(s.run=0;s.run<run_limit&&!stopped(&s)&&!OPTIMAL();s.run++) {
        if(!s.diagonal)runs++;
        int *order=orders[s.run];
        if(!s.diagonal) {
            for(int i=0;i<r->item_count;i++)order[i]=i;
            for(int i=1;i<r->item_count;i++){int v=order[i],j=i-1;while(j>=0&&sort_key(&r->items[order[j]],s.run%4)<sort_key(&r->items[v],s.run%4)){order[j+1]=order[j];j--;}order[j+1]=v;}
            if(s.run>=4)for(int i=r->item_count-1;i>0;i--){int j=(int)(random_u32(&s)%(unsigned)(i+1));int v=order[i];order[i]=order[j];order[j]=v;}
            /* Geometric orders preserve large/long/tall items before gaps
               fragment. Keep random diversity for stock/weight constraints.
               Consume the original shuffle draws above so later random
               orders remain identical for the same seed. */
            if(!capacity_limited&&(s.run==4||s.run==5)) {
                for(int i=0;i<r->item_count;i++)order[i]=i;
                for(int i=1;i<r->item_count;i++){int v=order[i],j=i-1;while(j>=0&&sort_key(&r->items[order[j]],s.run)<sort_key(&r->items[v],s.run)){order[j+1]=order[j];j--;}order[j+1]=v;}
            }
        }
        greedy(&s,order,trial,alternative,out);
        /* Anytime mode: try the local moves early, so that large orders reach
           them even when the full portfolio would use the whole budget. */
        if(r->options.improve&&!s.diagonal&&s.run==1&&!stopped(&s)&&!OPTIMAL())improve_bins(&s,orders,runs,out);
    }
    /* Preserve all greedy incumbents first, then use the remaining shared
       time/candidate budget to explore four box-choice prefixes per depth.
       These are continuations of the same restart orders and pose policies. */
    if(r->box_count>1&&!stopped(&s)&&!OPTIMAL()) {
        BoxState *states=calloc(BOX_BEAM_WIDTH*2,sizeof *states);
        if(states) {
            for(s.run=0;s.run<runs&&!stopped(&s)&&!OPTIMAL();s.run++)search_box_choices(&s,orders[s.run],out,states);
            free(states);
        }
    }
    }
    /* Leave the complete ordinary and XY portfolios their original priority.
       Refinement spends only their unused global budget. */
    s.diagonal=0;
    if(!OPTIMAL())refine_box_order(&s,orders,runs,out);
    if(!OPTIMAL())reinsert_box_items(&s,orders,runs,out);
    if(!OPTIMAL()&&runs)improve_bins(&s,orders,runs,out);
    if(r->options.improve&&runs) {
        /* Anytime phase: perturbed and random orders through the same greedy
           and box-choice search, then local moves, until a limit, a proven
           optimum, or (count and cost already proven) two idle rounds. */
        BoxState *states=r->box_count>1?calloc(BOX_BEAM_WIDTH*2,sizeof *states):NULL;
        int order[OP_MAX_ITEMS],idle=0;
        for(int iteration=0;!stopped(&s)&&!OPTIMAL();iteration++) {
            /* Count and cost proven: only the volume tie-break remains. */
            if(bound_reached(r,out,bound)&&idle>=2)break;
            OpResult saved=*out;
            int strength=iteration%5==4?-1:1+(int)(random_u32(&s)%(unsigned)(r->item_count/4+1));
            perturb(&s,orders[iteration%runs],order,r->item_count,strength);
            s.run=runs+iteration;s.diagonal=has_diagonals&&(iteration%2);
            greedy(&s,order,trial,alternative,out);
            if(states&&!stopped(&s)&&!OPTIMAL())search_box_choices(&s,order,out,states);
            s.diagonal=0;
            if(!stopped(&s)&&!OPTIMAL())improve_bins(&s,orders,runs,out);
            idle=better(r,out,&saved)?0:idle+1;
        }
        free(states);
    }
#undef OPTIMAL
    out->lower_bound=bound;out->proven_optimal=bound_reached(r,out,bound);
    free(s.cache);free(trial);free(alternative);out->elapsed_ms=op_now_ms()-start;out->candidates=s.candidates;out->restarts=runs;out->timed_out=s.timed_out;out->budget_exhausted=s.budget_exhausted;
    if(error&&error_size>0)error[0]=0;
    return 0;
}

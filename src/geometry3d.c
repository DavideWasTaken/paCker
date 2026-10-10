#include "geometry3d.h"
#include <float.h>
#include <math.h>
#include <string.h>

#ifdef __FAST_MATH__
#error "geometry3d requires IEEE arithmetic without fast-math"
#endif
/* Each elementary operation is enclosed by adjacent representable values.
   This works with either 53-bit or extended long double; no precision is
   assumed from its spelling. Keep intermediate arithmetic in separate
   volatile stores to prevent contraction/reassociation across operations.
   Exact zero/one identities avoid unnecessary uncertainty on orthogonal axes.
   Underflow is enclosed too; overflow/invalid intervals cannot prove validity. */
typedef Op3Interval I;
static I exact(long double x) { I r={x,x};return r; }
static int zero(I a) { return a.lo==0&&a.hi==0; }
static int one(I a) { return a.lo==1&&a.hi==1; }
static int arithmetic_supported(void) {
    volatile long double unit=1,ulp=DBL_EPSILON;
    volatile long double probe=unit+ulp;
    /* 1+2^-52 is exact in both admitted precision modes, independently of
       rounding direction. A 24-bit x87 caller cannot satisfy this check. */
    return probe==(long double)nextafter(1.0,INFINITY);
}
static int extended_arithmetic(void) {
    if(LDBL_MANT_DIG<=DBL_MANT_DIG)return 0;
    /* A DLL caller can change x87 precision control (CPython on Windows does).
       Check actual arithmetic, not just the compile-time storage format.
       Comparing against nextafterl also detects directed reduced precision. */
    volatile long double unit=1,ulp=LDBL_EPSILON;
    volatile long double probe=unit+ulp;
    return probe==nextafterl(unit,INFINITY);
}
static I rounded(long double lo,long double hi) {
    if(!extended_arithmetic()) {
        /* Enclose at least a full double ULP on platforms/callers performing
           53-bit arithmetic, even if long double storage has 64 mantissa bits. */
        I r={(long double)nextafter((double)lo,-INFINITY),
             (long double)nextafter((double)hi,INFINITY)};return r;
    }
    I r={nextafterl(lo,-INFINITY),nextafterl(hi,INFINITY)};return r;
}
static I neg(I a) { I r={-a.hi,-a.lo};return r; }
static I add(I a,I b) {
    if(zero(a))return b;
    if(zero(b))return a;
    volatile long double lo=a.lo+b.lo,hi=a.hi+b.hi;return rounded(lo,hi);
}
static I sub(I a,I b) {
    if(a.lo==a.hi&&b.lo==b.hi&&a.lo==b.lo)return exact(0);
    return add(a,neg(b));
}
static I mul(I a,I b) {
    if(zero(a)||zero(b))return exact(0);
    if(one(a))return b;
    if(one(b))return a;
    volatile long double p0=a.lo*b.lo,p1=a.lo*b.hi,p2=a.hi*b.lo,p3=a.hi*b.hi;
    return rounded(fminl(fminl(p0,p1),fminl(p2,p3)),fmaxl(fmaxl(p0,p1),fmaxl(p2,p3)));
}
static I divide(I a,I b) {
    if(zero(a)&&b.lo>0)return exact(0);
    if(one(b))return a;
    if(!(b.lo>0)) { I all={-INFINITY,INFINITY};return all; }
    volatile long double lo=1/b.hi,hi=1/b.lo;
    return mul(a,rounded(lo,hi));
}
static I absolute(I a) {
    if(a.lo>=0)return a;
    if(a.hi<=0)return neg(a);
    I r={0,fmaxl(-a.lo,a.hi)};return r;
}
static I square(I a) {
    a=absolute(a);I r=mul(a,a);if(r.lo<0)r.lo=0;return r;
}
static I root(I a) {
    if(zero(a))return a;
    I r=rounded(sqrtl(fmaxl(0,a.lo)),sqrtl(fmaxl(0,a.hi)));
    if(r.lo<0)r.lo=0;
    return r;
}
static I dot(const I a[3],const I b[3]) {
    I r=exact(0);for(int k=0;k<3;k++)r=add(r,mul(a[k],b[k]));return r;
}
static void cross(const I a[3],const I b[3],I r[3]) {
    for(int k=0;k<3;k++)r[k]=sub(mul(a[(k+1)%3],b[(k+2)%3]),mul(a[(k+2)%3],b[(k+1)%3]));
}
static int range(double x,double lo,double hi) {return isfinite(x)&&x>=lo&&x<=hi;}
static int margin_valid(double c) {return range(c,0,1e6);}
static int box_valid(const double b[3]) {
    return b&&range(b[0],1e-4,1e6)&&range(b[1],1e-4,1e6)&&range(b[2],1e-4,1e6);
}
static int pose_status(const Op3Pose *p) {
    if(!p||!range(p->width,1e-4,1e6)||!range(p->length,1e-4,1e6)||!range(p->height,1e-4,1e6))return OP3_INVALID;
    for(int k=0;k<3;k++)if(!isfinite(p->center[k]))return OP3_INVALID;
    I n=exact(0);
    for(int k=0;k<4;k++) {
        if(!range(p->orientation[k],-1.000001,1.000001))return OP3_INVALID;
        n=add(n,square(exact(p->orientation[k])));
    }
    /* Distinguish proof of validity, proof of invalidity, and a norm interval
       straddling a contract boundary. Uncertainty is not invalid input. */
    I unit_error=rounded(1e-12L,1e-12L);
    I lower=sub(exact(1),unit_error),upper=add(exact(1),unit_error);
    if(n.hi<lower.lo||n.lo>upper.hi)return OP3_INVALID;
    if(n.lo>=lower.hi&&n.hi<=upper.lo)return OP3_OK;
    return OP3_UNCERTAIN;
}
static I tolerance(double side) {
    I unit=rounded(1e-9L,1e-9L),scaled=mul(unit,exact(side));
    I r={fminl(unit.lo,scaled.lo),fminl(unit.hi,scaled.hi)};return r;
}
int op3_pose_canonicalize(const Op3Pose *p,Op3Pose *out) {
    Op3Pose local;
    if(p)local=*p;
    if(out)memset(out,0,sizeof *out);
    if(!out||!p)return OP3_INVALID;
    if(!arithmetic_supported())return OP3_UNCERTAIN;
    int status=pose_status(&local);if(status!=OP3_OK)return status;
    long double n=0;
    for(int k=0;k<4;k++)n+=(long double)local.orientation[k]*local.orientation[k];
    n=sqrtl(n);
    int order[4]={3,0,1,2},sign=1;
    for(int j=0;j<4;j++)if(local.orientation[order[j]]!=0) {sign=local.orientation[order[j]]<0?-1:1;break;}
    *out=local;
    for(int k=0;k<4;k++) {
        out->orientation[k]=(double)(sign*(long double)local.orientation[k]/n);
        if(out->orientation[k]==0)out->orientation[k]=0; /* clear signed zero */
    }
    return OP3_OK;
}
int op3_obb_build(const Op3Pose *p,Op3Obb *o) {
    if(o)memset(o,0,sizeof *o);
    if(!o||!p)return OP3_INVALID;
    if(!arithmetic_supported())return OP3_UNCERTAIN;
    int status=pose_status(p);if(status!=OP3_OK)return status;
    I q[4],n=exact(0),m[3][3];
    for(int k=0;k<4;k++) {q[k]=exact(p->orientation[k]);n=add(n,square(q[k]));}
    /* Rational form of the unit-quaternion matrix: normalizes without
       introducing an unnecessary square-root dependency. m[row][column]. */
    for(int k=0;k<3;k++)m[k][k]=sub(exact(1),divide(mul(exact(2),add(square(q[(k+1)%3]),square(q[(k+2)%3]))),n));
    m[0][1]=divide(mul(exact(2),sub(mul(q[0],q[1]),mul(q[2],q[3]))),n);
    m[1][0]=divide(mul(exact(2),add(mul(q[0],q[1]),mul(q[2],q[3]))),n);
    m[0][2]=divide(mul(exact(2),add(mul(q[0],q[2]),mul(q[1],q[3]))),n);
    m[2][0]=divide(mul(exact(2),sub(mul(q[0],q[2]),mul(q[1],q[3]))),n);
    m[1][2]=divide(mul(exact(2),sub(mul(q[1],q[2]),mul(q[0],q[3]))),n);
    m[2][1]=divide(mul(exact(2),add(mul(q[1],q[2]),mul(q[0],q[3]))),n);
    double sides[3]={p->width,p->length,p->height};
    o->smallest_side=fmin(sides[0],fmin(sides[1],sides[2]));
    for(int k=0;k<3;k++) {
        o->center[k]=p->center[k];o->half[k]=(long double)sides[k]/2;
        for(int j=0;j<3;j++) {
            o->axes[j][k]=m[k][j];o->matrix[k][j]=m[k][j].lo/2+m[k][j].hi/2;
        }
        o->bounds[k].lo=INFINITY;o->bounds[k].hi=-INFINITY;
        o->aabb[k][0]=INFINITY;o->aabb[k][1]=-INFINITY;
    }
    for(int v=0;v<8;v++)for(int k=0;k<3;k++) {
        I value=exact(o->center[k]);long double nominal=o->center[k];
        for(int j=0;j<3;j++) {
            long double h=(v&(1<<j))?o->half[j]:-o->half[j];
            value=add(value,mul(o->axes[j][k],exact(h)));
            nominal+=o->matrix[k][j]*h;
        }
        o->vertex_bounds[v][k]=value;o->vertices[v][k]=nominal;
        o->bounds[k].lo=fminl(o->bounds[k].lo,value.lo);o->bounds[k].hi=fmaxl(o->bounds[k].hi,value.hi);
        o->aabb[k][0]=fminl(o->aabb[k][0],nominal);o->aabb[k][1]=fmaxl(o->aabb[k][1],nominal);
    }
    o->valid=1;return OP3_OK;
}
int op3_vertices(const Op3Pose *p,double out[8][3]) {
    if(out)memset(out,0,8*3*sizeof(double));
    if(!out)return OP3_INVALID;
    Op3Obb o;int rc=op3_obb_build(p,&o);if(rc)return rc;
    for(int v=0;v<8;v++)for(int k=0;k<3;k++) {
        if(fabsl(o.vertices[v][k])>DBL_MAX) {memset(out,0,8*3*sizeof(double));return OP3_UNCERTAIN;}
        out[v][k]=(double)o.vertices[v][k];
    }
    return OP3_OK;
}
int op3_obb_inside(const Op3Obb *o,const double b[3],double c,int *inside) {
    if(inside)*inside=0;
    if(!inside||!o||!o->valid||!box_valid(b)||!margin_valid(c))return OP3_INVALID;
    if(!arithmetic_supported())return OP3_UNCERTAIN;
    double smallest=fmin(o->smallest_side,fmin(b[0],fmin(b[1],b[2])));
    I e=tolerance(smallest);int uncertain=0;
    for(int v=0;v<8;v++)for(int k=0;k<3;k++) {
        I lower=add(sub(o->vertex_bounds[v][k],exact(c)),e);
        I upper=add(sub(sub(exact(b[k]),o->vertex_bounds[v][k]),exact(c)),e);
        if(lower.hi<0||upper.hi<0)return OP3_OK;
        if(!(lower.lo>=0)||!(upper.lo>=0))uncertain=1;
    }
    if(uncertain)return OP3_UNCERTAIN;
    *inside=1;return OP3_OK;
}
/* Project using cached axes and local radii. The scaled e*|axis| threshold
   avoids dividing by very short cross axes. A zero/uncertain cross axis
   cannot establish separation. No epsilon is added to a rotation matrix. */
typedef struct { I delta[3],half_a[3],half_b[3],epsilon; } Projections;
static I separation(const Op3Obb *a,const Op3Obb *b,const I axis[3],const Projections *p) {
    I norm=exact(0),r=exact(0);
    for(int k=0;k<3;k++)norm=add(norm,square(axis[k]));
    for(int j=0;j<3;j++) {
        I ra=mul(p->half_a[j],absolute(dot(a->axes[j],axis)));
        I rb=mul(p->half_b[j],absolute(dot(b->axes[j],axis)));
        r=add(r,add(ra,rb)); /* Symmetric grouping under a <-> b. */
    }
    return add(sub(absolute(dot(p->delta,axis)),r),mul(p->epsilon,root(norm)));
}
int op3_obb_intersects(const Op3Obb *a,const Op3Obb *b,double c,int *hit) {
    if(hit)*hit=1;
    if(!hit||!a||!b||!a->valid||!b->valid||!margin_valid(c))return OP3_INVALID;
    if(!arithmetic_supported())return OP3_UNCERTAIN;
    I e=tolerance(fmin(a->smallest_side,b->smallest_side)),padding=exact((long double)c/2);
    /* Reuse translation, expanded half-sides, and cached axis matrices across
       all projections. Translation before projection avoids world-coordinate
       cancellation of thin cuboids placed far from the origin. */
    Projections p;p.epsilon=e;
    for(int k=0;k<3;k++) {
        p.delta[k]=sub(exact(a->center[k]),exact(b->center[k]));
        p.half_a[k]=add(exact(a->half[k]),padding);
        p.half_b[k]=add(exact(b->half[k]),padding);
    }
    /* Conservative cached AABB prefilter includes the expanded OBBs. */
    for(int k=0;k<3;k++) {
        I expansion=exact(0);
        for(int j=0;j<3;j++)expansion=add(expansion,mul(padding,add(absolute(a->axes[j][k]),absolute(b->axes[j][k]))));
        I forward=sub(exact(b->bounds[k].lo),exact(a->bounds[k].hi));
        I reverse=sub(exact(a->bounds[k].lo),exact(b->bounds[k].hi));
        I adjustment=sub(e,expansion);
        if(add(forward,adjustment).lo>=0||add(reverse,adjustment).lo>=0) {*hit=0;return OP3_OK;}
    }
    int uncertain=0;
    for(int i=0;i<15;i++) {
        I axis[3];
        if(i<3)memcpy(axis,a->axes[i],sizeof axis);
        else if(i<6)memcpy(axis,b->axes[i-3],sizeof axis);
        else cross(a->axes[(i-6)/3],b->axes[(i-6)%3],axis);
        if(zero(axis[0])&&zero(axis[1])&&zero(axis[2]))continue;
        I s=separation(a,b,axis,&p);
        /* Nonzero interval lower bound is required: an interval axis that
           might be zero never proves separation, including s==0. */
        int nonzero=axis[0].lo>0||axis[0].hi<0||axis[1].lo>0||axis[1].hi<0||axis[2].lo>0||axis[2].hi<0;
        if(nonzero&&s.lo>=0) {*hit=0;return OP3_OK;}
        if(!(s.hi<0))uncertain=1;
    }
    return uncertain?OP3_UNCERTAIN:OP3_OK;
}
int op3_inside(const Op3Pose *p,const double b[3],double c,int *inside) {
    if(inside)*inside=0;
    if(!inside||!box_valid(b)||!margin_valid(c))return OP3_INVALID;
    Op3Obb o;int rc=op3_obb_build(p,&o);if(rc)return rc;
    return op3_obb_inside(&o,b,c,inside);
}
int op3_intersects(const Op3Pose *a,const Op3Pose *b,double c,int *hit) {
    if(hit)*hit=1;
    if(!hit||!margin_valid(c))return OP3_INVALID;
    Op3Obb oa,ob;int rc=op3_obb_build(a,&oa);if(rc)return rc;
    rc=op3_obb_build(b,&ob);if(rc)return rc;
    return op3_obb_intersects(&oa,&ob,c,hit);
}

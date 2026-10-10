#include "packer3d.h"
#include "../src/geometry3d.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static Op3Pose pose(double x,double y,double z,double w,double l,double h) {
    Op3Pose p={w,l,h,{x,y,z},{0,0,0,1}};return p;
}
static int inside(Op3Pose p,double side,double margin) {
    double box[3]={side,side,side};int yes=99;
    int rc=op3_inside(&p,box,margin,&yes);
    assert(rc==OP3_OK||rc==OP3_UNCERTAIN);return yes;
}
static int hit(Op3Pose a,Op3Pose b,double margin) {
    int ab=99,ba=99;int ra=op3_intersects(&a,&b,margin,&ab);
    int rb=op3_intersects(&b,&a,margin,&ba);
    assert(ra==OP3_OK||ra==OP3_UNCERTAIN);
    assert(rb==OP3_OK||rb==OP3_UNCERTAIN);assert(ab==ba);return ab;
}
int main(void) {
    Op3Pose a=pose(1,2,3,2,4,6),b=a,out;double v[8][3];
    assert(op3_vertices(&a,v)==OP3_OK);
    assert(v[0][0]==0&&v[0][1]==0&&v[0][2]==0);
    assert(v[7][0]==2&&v[7][1]==4&&v[7][2]==6);
    a.orientation[2]=sqrt(.5);a.orientation[3]=sqrt(.5);
    assert(op3_vertices(&a,v)==OP3_OK);
    assert(fabs(v[0][0]-3)<1e-12&&fabs(v[0][1]-1)<1e-12&&fabs(v[0][2])<1e-12);
    a.orientation[2]*=-1;a.orientation[3]*=-1;
    assert(op3_pose_canonicalize(&a,&out)==OP3_OK&&out.orientation[3]>0);
    assert(op3_pose_canonicalize(&a,&a)==OP3_OK&&a.orientation[3]>0);
    a=pose(1,1,1,2,2,2);assert(inside(a,2,0));
    b=a;b.center[0]+=2;assert(!hit(a,b,0));
    b.center[1]+=2;assert(!hit(a,b,0));
    b.center[2]+=2;assert(!hit(a,b,0));
    b=a;b.center[0]+=2-5e-10;assert(!hit(a,b,0));
    b.center[0]=a.center[0]+2-5e-9;assert(hit(a,b,0));
    b=a;b.center[0]+=2;assert(hit(a,b,.01));
    b.center[0]+=.01;assert(!hit(a,b,.01));
    a=pose(1.1,1.1,1.1,2,2,2);assert(inside(a,2.2,.1));
    assert(!inside(a,2.2,.10001));
    a=pose(1-5e-10,1,1,2,2,2);assert(inside(a,2,0));
    a.center[0]=1-5e-9;assert(!inside(a,2,0));
    const double sizes[]={1e-4,1,1e6};
    for(int i=0;i<3;i++) {
        double s=sizes[i],e=fmin(1e-9,1e-9*s);
        a=pose(s/2,s/2,s/2,s,s,s);b=a;b.center[0]+=s;
        assert(!hit(a,b,0));b.center[0]-=10*e;assert(hit(a,b,0));
        assert(inside(a,s,0));
    }
    a=pose(0,0,0,1e6,1e-4,1e-4);b=a;
    b.orientation[2]=1e-14;b.orientation[3]=1;
    b.center[1]=5e-5;assert(hit(a,b,0));
    b.center[1]=.01;assert(!hit(a,b,0));
    /* Quaternion from a right-handed u,v,w triad. */
    a=pose(50,50,50,150,8,8);
    a.orientation[0]=.8804762392171493;a.orientation[1]=.3647051996310009;
    a.orientation[2]=.2798481423331213;a.orientation[3]=-.11591689595929514;
    assert(inside(a,100,0));
    Op3Obb obb;assert(op3_obb_build(&a,&obb)==OP3_OK);
    assert(obb.aabb[0][1]-obb.aabb[0][0]<96);
    assert(obb.aabb[2][1]-obb.aabb[2][0]<94);
    /* Large translated coordinates do not make tiny overlaps disappear. */
    a=pose(1e12,1e12,1e12,1e-4,1e-4,1e-4);b=a;
    assert(hit(a,b,0));b.center[0]=nextafter(1e12,INFINITY);assert(!hit(a,b,0));
    a=pose(1e30,1e30,1e30,2,2,2);b=a;assert(hit(a,b,0));
    assert(!inside(a,100,0));
    a=pose(1,1,1,2,2,2);double box[3]={2,2,2};int result;
    double bad[]={NAN,INFINITY,-INFINITY};
    for(int i=0;i<3;i++) {
        b=a;b.center[0]=bad[i];result=1;
        assert(op3_inside(&b,box,0,&result)==OP3_INVALID&&result==0);
        result=0;assert(op3_intersects(&a,&b,0,&result)==OP3_INVALID&&result==1);
        b=a;b.orientation[1]=bad[i];assert(op3_vertices(&b,v)==OP3_INVALID);
        b=a;b.height=bad[i];assert(op3_vertices(&b,v)==OP3_INVALID);
        assert(op3_inside(&a,box,bad[i],&result)==OP3_INVALID&&result==0);
    }
    b=a;b.orientation[3]=0;assert(op3_vertices(&b,v)==OP3_INVALID);
    for(int k=0;k<8;k++)for(int j=0;j<3;j++)assert(v[k][j]==0);
    b=a;b.orientation[3]=2;assert(op3_vertices(&b,v)==OP3_INVALID);
    b=a;b.width=0;assert(op3_vertices(&b,v)==OP3_INVALID);
    b=a;b.width=1e-5;assert(op3_vertices(&b,v)==OP3_INVALID);
    assert(op3_inside(&a,box,-1,&result)==OP3_INVALID);
    assert(op3_inside(&a,box,1e6+1,&result)==OP3_INVALID);
    assert(op3_inside(NULL,box,0,&result)==OP3_INVALID&&result==0);
    assert(op3_inside(&a,box,0,NULL)==OP3_INVALID);
    assert(op3_intersects(&a,&a,0,NULL)==OP3_INVALID);
    box[1]=NAN;assert(op3_inside(&a,box,0,&result)==OP3_INVALID);
#if (defined(__i386__)||defined(__x86_64__))&&(defined(__GNUC__)||defined(__clang__))
    /* Deliberately unsupported 24-bit x87 arithmetic must fail closed too.
       Test restores the caller environment before checking results. */
    unsigned short saved,low_precision;
    __asm__ __volatile__("fnstcw %0":"=m"(saved));
    low_precision=(unsigned short)(saved&~0x300u);
    __asm__ __volatile__("fldcw %0"::"m"(low_precision));
    box[1]=2;int low_inside=99,low_hit=99;
    int ri=op3_inside(&a,box,0,&low_inside);
    int rh=op3_intersects(&a,&a,0,&low_hit);
    __asm__ __volatile__("fldcw %0"::"m"(saved));
    assert(ri==OP3_UNCERTAIN&&low_inside==0);
    assert(rh==OP3_UNCERTAIN&&low_hit==1);
    /* Reproduce the Windows DLL's effective 53-bit arithmetic explicitly on
       either x87 platform. A norm inside the threshold cannot be INVALID. */
    unsigned short double_precision=(unsigned short)((saved&~0x300u)|0x200u);
    __asm__ __volatile__("fldcw %0"::"m"(double_precision));
    b=a;b.orientation[3]=0.9999999999995001;
    int cr=op3_pose_canonicalize(&b,&out);
    int br=op3_obb_build(&b,&obb);
    int vr=op3_vertices(&b,v);
    ri=op3_inside(&b,box,0,&low_inside);
    rh=op3_intersects(&b,&a,0,&low_hit);
    __asm__ __volatile__("fldcw %0"::"m"(saved));
    assert(cr==OP3_UNCERTAIN&&br==OP3_UNCERTAIN&&vr==OP3_UNCERTAIN);
    assert(out.width==0&&out.orientation[3]==0&&!obb.valid);
    assert(v[0][0]==0&&v[7][2]==0);
    assert(ri==OP3_UNCERTAIN&&low_inside==0);
    assert(rh==OP3_UNCERTAIN&&low_hit==1);
#endif
    printf("geometry3d: contacts, tolerance, clearance, transforms, extreme scales, invalid input OK (LDBL_MANT_DIG=%d)\n",LDBL_MANT_DIG);
    return 0;
}

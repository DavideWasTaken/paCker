/* Private necessary-condition checks, without changing the public API. */
#include "../src/oblique.c"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>

static void check(const OpPlacement *p,const OpPlacement *faces,int count) {
    Shape a=shape(p);SupportBounds bounds;support_bounds(p,a,faces,count,&bounds);
    if(op_supported(p,faces,count)) {
        assert(!outside_support_bounds(p,a,&bounds));
        for(int axis=0;axis<2;axis++) {
            double positions[]={axis?p->y:p->x};int begin=0,end=1;
            /* Inside-box poses have coordinates bounded by box dimensions.
               This extent also exercises translated private support poses. */
            double extent=fmax(fabs(p->x)+a.hx,fabs(p->y)+a.hy);
            if(bounds.enabled) {
                support_position_range(positions,&begin,&end,axis?a.hy:a.hx,
                                       axis?bounds.bottom:bounds.left,axis?bounds.top:bounds.right,
                                       bounds.allowance+64*DBL_EPSILON*extent);
                assert(begin==0&&end==1);
            }
            support_row_range(p,a,&bounds,axis,positions,&begin,&end);
            assert(begin==0&&end==1);
        }
    }
}

int main(void) {
    double sizes[]={.0001,.001,1,100,100000,1000000};
    double centers[]={0,1000000,-1000000};
    for(int si=0;si<6;si++)for(int ci=0;ci<3;ci++)for(int turn=0;turn<4;turn++) {
        double d=sizes[si],c=centers[ci];
        OpPlacement faces[3]={{0,0,c-d/2,c,0,d,2*d,1,0},
                              {1,0,c+d/2,c,0,d,2*d,1,0},
                              {2,0,c,c,0,2*d,2*d,1.1,15}};
        OpPlacement p={3,0,c,c,1,d,d,.0001,turn*90};
        for(int x=-5;x<=5;x++)for(int y=-5;y<=5;y++) {
            p.x=c+x*d/4;p.y=c+y*d/4;check(&p,faces,3);
        }
        p.x=c;p.y=c;
        for(int edge=-1;edge<=1;edge+=2)for(int axis=0;axis<2;axis++)
            for(int delta=-2;delta<=2;delta++) {
                double position=c+edge*d/2+delta*geometric_epsilon(&p)/2;
                if(axis)p.y=position;else p.x=position;
                check(&p,faces,3);p.x=c;p.y=c;
            }
        SupportBounds bounds;
        p.z=0;support_bounds(&p,shape(&p),faces,3,&bounds);assert(!bounds.enabled);
        p.z=1;faces[2].height=1;
        support_bounds(&p,shape(&p),faces,3,&bounds);assert(!bounds.enabled);
        p.angle=15;support_bounds(&p,shape(&p),faces,2,&bounds);assert(!bounds.enabled);
    }
    OpPlacement base={0,0,0,0,0,1,1,1,0},p={1,0,100,100,1,1,1,1,0};
    SupportBounds bounds;support_bounds(&p,shape(&p),&base,1,&bounds);
    assert(outside_support_bounds(&p,shape(&p),&bounds));
    p.z=2;support_bounds(&p,shape(&p),&base,1,&bounds);
    assert(outside_support_bounds(&p,shape(&p),&bounds));
    /* Unrelated faces can subdivide an unsupported outer strip into slabs
       that the validator skips individually. Row pruning must allow their
       accumulated tolerance, not just the candidate's single epsilon. */
    p=(OpPlacement){4,0,.5,.5,1,1,1,1,0};
    double e=geometric_epsilon(&p);
    OpPlacement slivers[4]={{0,0,-.00005+e*.5,.2,0,.0001,.1,1,0},
                             {1,0,-.00005+e,.4,0,.0001,.1,1,0},
                             {2,0,-.00005+e*1.5,.6,0,.0001,.1,1,0},
                             {3,0,.5+e, .5,0,1-2*e,1,1,0}};
    assert(op_supported(&p,slivers,4));check(&p,slivers,4);
    puts("support bounds: full coverage, edge tolerance, numeric scales and oblique fallback passed");
    return 0;
}

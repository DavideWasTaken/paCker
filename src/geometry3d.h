#ifndef GEOMETRY3D_H
#define GEOMETRY3D_H
#include "packer3d.h"
/* Interval caches are private, valid only after successful construction.
   aabb and vertices are nominal values for candidate generation; use the
   checked functions for validity. Never modify a cached OBB's members. */
typedef struct { long double lo,hi; } Op3Interval;
typedef struct {
    long double center[3],half[3],matrix[3][3],vertices[8][3],aabb[3][2];
    Op3Interval axes[3][3],vertex_bounds[8][3],bounds[3];
    double smallest_side;
    int valid;
} Op3Obb;
int op3_obb_build(const Op3Pose *pose,Op3Obb *obb);
int op3_obb_inside(const Op3Obb *obb,const double box[3],double clearance,int *inside);
int op3_obb_intersects(const Op3Obb *a,const Op3Obb *b,double clearance,int *intersects);
#endif

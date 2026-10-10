#ifndef OBLIQUE_H
#define OBLIQUE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define OP_MAX_ITEMS 256
#define OP_MAX_BOXES 64
#define OP_ID_SIZE 64
#define OP_VERSION "0.5.0"
typedef enum { OP_NONE=0, OP_FLAT=1, OP_ANY=2 } OpRotation;
/* STABLE (default): on the floor, or the footprint centre lies over the
   convex hull of the product's contacts with lower top faces, so a uniform
   rigid product does not tip. CONTACT: any positive overlap, nothing floats
   (fillers assumed). FULL_BASE: the whole footprint is supported. */
typedef enum { OP_SUPPORT_FULL_BASE=0, OP_SUPPORT_CONTACT=1, OP_SUPPORT_STABLE=2 } OpSupport;
/* Caller expands quantities. instance is a zero-based index within its item id. */
typedef struct {
    char id[OP_ID_SIZE];
    double width,length,height,weight;
    int instance, rotation, diagonal;
} OpItem;
typedef struct {
    char id[OP_ID_SIZE];
    double width,length,height,max_weight,cost;
    int quantity; /* -1 unlimited, 0 unavailable */
} OpBox;
typedef struct {
    double angle_step,time_limit_ms,gap;
    uint64_t max_candidates;
    unsigned seed;
    int restarts;
    int support; /* OpSupport */
    int improve; /* 1: keep improving until a limit or a proven lower bound */
} OpOptions;
typedef struct {
    OpItem items[OP_MAX_ITEMS];
    OpBox boxes[OP_MAX_BOXES];
    int item_count,box_count;
    OpOptions options;
} OpRequest;
typedef struct {
    int item_index,bin_index;
    double x,y,z,width,length,height,angle;
} OpPlacement;
typedef struct {
    int box_index;
    double weight;
} OpBin;
typedef struct {
    OpPlacement placements[OP_MAX_ITEMS];
    OpBin bins[OP_MAX_ITEMS];
    int unpacked[OP_MAX_ITEMS];
    int placement_count,bin_count,unpacked_count;
    double total_cost,utilization,elapsed_ms;
    uint64_t candidates;
    int restarts,timed_out,budget_exhausted;
    int lower_bound; /* boxes needed by any complete solution (volume, weight, size) */
    int proven_optimal; /* complete, and no solution can use fewer boxes or less cost */
} OpResult;
void op_default_options(OpOptions *options);
/* 0 on valid request, including partial solutions. Invalid arguments return 1. */
int op_pack(const OpRequest *request,OpResult *result,char *error,int error_size);
/* Public geometry helpers use the same center XY / bottom Z convention. */
int op_intersects(const OpPlacement *a,const OpPlacement *b,double gap);
int op_inside(const OpPlacement *p,const OpBox *b,double gap);
/* Full footprint on floor or the union of coplanar top faces. The placed
   list must already consist of valid, mutually non-overlapping solids;
   count must be in [0, OP_MAX_ITEMS]. */
int op_supported(const OpPlacement *p,const OpPlacement *placed,int count);
/* On the floor, or overlapping a coplanar top face with positive area. */
int op_rests(const OpPlacement *p,const OpPlacement *placed,int count);
/* Rests, and the footprint centre is inside the convex hull of the contacts. */
int op_stable(const OpPlacement *p,const OpPlacement *placed,int count);
double op_now_ms(void);
#ifdef __cplusplus
}
#endif
#endif

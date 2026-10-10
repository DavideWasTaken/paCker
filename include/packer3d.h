#ifndef PACKER3D_H
#define PACKER3D_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Separate API: no change to the ordinary Op* ABI. No physics/support rule. */
#define OP3_VERSION "0.5.1-free3d-dev"
#define OP3_MAX_ITEMS 256
#define OP3_MAX_BOXES 64
#define OP3_ID_SIZE 64
typedef enum { OP3_NONE=0, OP3_FLAT=1, OP3_ANY=2, OP3_FREE3D=3 } Op3Rotation;
typedef enum { OP3_OK=0, OP3_INVALID=1, OP3_UNCERTAIN=2 } Op3Status;
/* Original sides, right-handed X=width,Y=length,Z=height; center, not bottom Z.
   Active local-to-container quaternion [x,y,z,w]. Squared norm must differ
   from 1 by <=1e-12. Geometry uses its exactly normalized mathematical rotation.
   Canonical sign: first nonzero component in w,x,y,z order is positive.
   Dimensions are finite [1e-4,1e6]; centers are any finite doubles. */
typedef struct {
    double width,length,height;
    double center[3],orientation[4];
} Op3Pose;
typedef struct {
    char id[OP3_ID_SIZE];
    double width,length,height,weight;
    int instance,rotation,diagonal;
} Op3Item;
typedef struct {
    char id[OP3_ID_SIZE];
    double width,length,height,max_weight,cost;
    int quantity; /* -1 unlimited; 0 unavailable */
} Op3Box;
typedef struct {
    double angle_step,time_limit_ms,clearance;
    uint64_t max_candidates;
    unsigned seed;
    int restarts;
} Op3Options;
typedef struct {
    Op3Item items[OP3_MAX_ITEMS];
    Op3Box boxes[OP3_MAX_BOXES];
    int item_count,box_count;
    Op3Options options;
} Op3Request;
typedef struct { int item_index,bin_index; Op3Pose pose; } Op3Placement;
typedef struct { int box_index; double weight; } Op3Bin;
typedef enum {
    OP3_SEARCH_EXHAUSTED=0, OP3_COMPLETED=1,
    OP3_TIME_LIMIT=2, OP3_CANDIDATE_LIMIT=3
} Op3StopReason;
/* Search will preserve the ordinary lexicographic objective:
   (unpacked count, total cost, bin count, total box volume), stock and weight. */
typedef struct {
    Op3Placement placements[OP3_MAX_ITEMS];
    Op3Bin bins[OP3_MAX_ITEMS];
    int unpacked[OP3_MAX_ITEMS];
    int placement_count,bin_count,unpacked_count;
    double total_cost,utilization,elapsed_ms;
    uint64_t candidates;
    int restarts,timed_out,budget_exhausted;
    int stop_reason;
    uint64_t xy_candidates;
    double xy_elapsed_ms;
} Op3Result;

/* Authoritative version of the linked geometric engine. */
const char *op3_version(void);
void op3_default_options(Op3Options *options);
/* 0 for a valid request, including partial/empty results; 1 on invalid
   arguments or allocation failure. Result is zeroed on failure; a bounded
   diagnostic is written if error!=NULL and error_size>0. Caller expands
   quantities; (id,instance) identifies each product. No support/physics check.
   Candidate: one canonical double pose submitted to the full containment and
   pair validator. Generation/prechecks do not increment this count, but share
   the cooperative time budget. Phase limits never assert global stop flags.
   max_candidates bounds deterministic work; time-limited outcomes may vary.
   xy_* report actual initialization usage (zero when no free3d is present).
   Existing ordinary structures, symbols and serialization are unaffected. */
int op3_pack(const Op3Request *request,Op3Result *result,char *error,int error_size);

/* All functions return Op3Status. NULL or invalid inputs return INVALID.
   If arithmetic cannot certify which side of the quaternion norm threshold
   an input lies on, it returns UNCERTAIN rather than classifying it INVALID.
   On INVALID/UNCERTAIN, predicates fail closed: inside=0, intersects=1.
   Non-predicate output arrays/poses are zeroed on failure (if non-NULL).
   Arithmetic below 53 effective mantissa bits returns UNCERTAIN. Effective
   x87 precision is checked at runtime; the caller environment is preserved.
   Vertices use bit 0=X positive, bit 1=Y positive, bit 2=Z positive.
   Vertex output is rounded to double for interchange; predicates retain bounds.
   Canonicalization accepts in-place operation. */
int op3_pose_canonicalize(const Op3Pose *pose,Op3Pose *canonical);
int op3_vertices(const Op3Pose *pose,double vertices[8][3]);
/* Box origin is (0,0,0). Clearance finite [0,1e6]. Wall distance >=clearance-e;
   pair test expands EACH local half-side by clearance/2, not Euclidean offset.
   e=min(1e-9,1e-9*smallest side) among the involved original cuboids.
   Penetration/overshoot <=e counts as contact. Uncertain arithmetic never
   increases e. Contact is not intersection. No support/equilibrium test. */
int op3_inside(const Op3Pose *pose,const double box[3],double clearance,int *inside);
int op3_intersects(const Op3Pose *a,const Op3Pose *b,double clearance,int *intersects);
#ifdef __cplusplus
}
#endif
#endif

#ifndef SEARCH3D_H
#define SEARCH3D_H
#include "packer3d.h"
double op3_search_now_ms(void);
/* Internal, request already checked; returns nonzero on allocation failure. */
int op3_search(const Op3Request *request,Op3Result *result,double start);
#endif

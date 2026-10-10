#ifndef JSON3D_H
#define JSON3D_H
#include "packer3d.h"
#include "../third_party/cJSON.h"
/* CLI validates the complete strict UTF-8 JSON stream before this conversion. */
int op3_request_from_json(const cJSON *root, Op3Request *request, char *error);
cJSON *op3_result_to_json(const Op3Request *request, const Op3Result *result);
#endif

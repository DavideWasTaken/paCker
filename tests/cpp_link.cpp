// A C++ consumer links the C libraries without compiling the engines as C++.
#include "oblique.h"
#include "packer3d.h"
int main() {
    OpOptions ordinary{};
    Op3Options geometric{};
    op_default_options(&ordinary);
    op3_default_options(&geometric);
    return ordinary.max_candidates && geometric.max_candidates ? 0 : 1;
}

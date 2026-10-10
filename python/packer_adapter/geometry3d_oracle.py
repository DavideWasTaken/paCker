"""Independent 60-digit geometric verifier, with no C predicates/dependencies.

Input numbers have the semantics of a parsed C double: convert to float once,
then Decimal.from_float (never Decimal(str(float))). Near-unit quaternions are
normalized mathematically. Faces and edges are recovered from all real vertices;
the SAT projections enumerate vertices rather than the C center/radius shortcut.
"""
import copy
from decimal import Decimal, localcontext
import math

PRECISION = 60
ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('expected a finite double') from exc
    if not math.isfinite(value):
        raise ValueError('expected a finite double')
    return Decimal.from_float(value)


def _sides(p):
    sides = [number(p[k]) for k in ('width', 'length', 'height')]
    if any(not 1e-4 <= float(x) <= 1e6 for x in sides):
        raise ValueError('dimensions outside [1e-4,1e6]')
    return sides


def _pose(p):
    try:
        sides = _sides(p)
        if len(p['center']) != 3 or len(p['orientation']) != 4:
            raise ValueError('invalid vector size')
        center = [number(x) for x in p['center']]
        q = [number(x) for x in p['orientation']]
    except (KeyError, TypeError) as exc:
        raise ValueError('invalid pose') from exc
    norm2 = sum(x*x for x in q)
    if abs(norm2 - ONE) > Decimal('1e-12'):
        raise ValueError('quaternion is not unit within squared-norm tolerance')
    norm = norm2.sqrt()
    return sides, center, [x/norm for x in q]


def _margin(clearance):
    c = number(clearance)
    if c < 0 or c > Decimal(1000000):
        raise ValueError('clearance outside [0,1e6]')
    return c


def _add(a, b):
    return tuple(x+y for x, y in zip(a, b))


def _sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _vertices(sides, center, q, expansion=ZERO):
    # Rotate each individual vector via q*v*q^-1, independently of C's matrix.
    result = []
    qv = q[:3]
    for i in range(8):
        v = tuple((ONE if i & (1 << k) else -ONE)*(sides[k]+expansion)/TWO for k in range(3))
        uv = _cross(qv, v)
        uuv = _cross(qv, uv)
        result.append(tuple(center[k] + v[k] + TWO*(q[3]*uv[k]+uuv[k]) for k in range(3)))
    return tuple(result)


def vertices(p):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return _vertices(*_pose(p))


def canonicalize(p):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        _, _, q = _pose(p)
        if next(x for x in (q[3], q[0], q[1], q[2]) if x) < 0:
            q = [-x for x in q]
        result = copy.deepcopy(p)
        result['orientation'] = [float(x) if x else 0 for x in q]
        return result


def inside(p, box, clearance=0):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        sides, center, q = _pose(p)
        try:
            if len(box) != 3:
                raise ValueError('box needs three sides')
            bounds = [number(x) for x in box]
        except TypeError as exc:
            raise ValueError('invalid box') from exc
        if any(not 1e-4 <= float(x) <= 1e6 for x in bounds):
            raise ValueError('invalid box dimensions')
        c = _margin(clearance)
        e = min(Decimal('1e-9'), Decimal('1e-9')*min(sides+bounds))
        return all(c-e <= v[k] <= bounds[k]-c+e
                   for v in _vertices(sides, center, q) for k in range(3))


def _edges(vs):
    return [_sub(vs[i], vs[0]) for i in (1, 2, 4)]


def _faces(edges):
    return [_cross(edges[0], edges[1]), _cross(edges[1], edges[2]), _cross(edges[2], edges[0])]


def intersects(a, b, clearance=0):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        sa, ca, qa = _pose(a)
        sb, cb, qb = _pose(b)
        c = _margin(clearance)
        e = min(Decimal('1e-9'), Decimal('1e-9')*min(sa+sb))
        # Translate before generating vertices. This preserves tiny dimensions
        # even when world coordinates are close to the largest finite double.
        va = _vertices(sa, (ZERO, ZERO, ZERO), qa, c)
        vb_local = _vertices(sb, (ZERO, ZERO, ZERO), qb, c)
        ea, eb = _edges(va), _edges(vb_local)
        vb = tuple(_add(v, _sub(cb, ca)) for v in vb_local)
        axes = _faces(ea)+_faces(eb)+[_cross(x, y) for x in ea for y in eb]
        for axis in axes:
            norm2 = _dot(axis, axis)
            if not norm2:
                continue
            norm = norm2.sqrt()
            # Normalize face/edge normals, then explicitly project every vertex.
            axis = tuple(x/norm for x in axis)
            pa, pb = [_dot(v, axis) for v in va], [_dot(v, axis) for v in vb]
            if min(pb)-max(pa) >= -e or min(pa)-max(pb) >= -e:
                return False
        return True


def rod_pose():
    """Construct the analytic orthonormal triad, then round to doubles."""
    u = [1/math.sqrt(3)]*3
    v = [1/math.sqrt(2), -1/math.sqrt(2), 0]
    w = [1/math.sqrt(6), 1/math.sqrt(6), -2/math.sqrt(6)]
    m = [[u[i], v[i], w[i]] for i in range(3)]
    # Largest-diagonal matrix-to-quaternion branch (x is largest here).
    s = 2*math.sqrt(1+m[0][0]-m[1][1]-m[2][2])
    q = [s/4, (m[0][1]+m[1][0])/s, (m[0][2]+m[2][0])/s, (m[2][1]-m[1][2])/s]
    return dict(width=150, length=8, height=8, center=[50, 50, 50], orientation=q)

"""Independent Decimal polygon geometry in physical units and local frames.

Inputs are the reported binary floats, not repaired placements. Higher precision
reduces cancellation for long/thin poses; this is not exact real arithmetic.
"""
from decimal import Decimal, localcontext
from functools import lru_cache

PRECISION = 60
PI = Decimal('3.141592653589793238462643383279502884197169399375105820974944592307816')
ZERO, ONE = Decimal(0), Decimal(1)
EPSILON = Decimal('1e-9')


def decimal(value):
    return Decimal.from_float(value) if isinstance(value, float) else Decimal(value)


def epsilon(p):
    return EPSILON * min(ONE, *(decimal(p[k]) for k in ('width', 'length', 'height')))


@lru_cache(maxsize=1024)
def axes(angle):
    """Unit axes, exact at quarter turns; other angles use a convergent series."""
    with localcontext() as context:
        value = decimal(angle)
        # Exact remainder needs room for the quotient even for a finite 1e308.
        context.prec = max(PRECISION, value.adjusted()+3)
        degrees = value % 360
        if degrees < 0:
            degrees += 360
        turns = {0: (ONE, ZERO), 90: (ZERO, ONE),
                 180: (-ONE, ZERO), 270: (ZERO, -ONE)}
        if degrees in turns:
            return turns[degrees]
        if degrees > 180:
            degrees -= 360
        context.prec = PRECISION
        radians = degrees * PI / 180
        cosine = term_c = ONE
        sine = term_s = radians
        square = -radians * radians
        for n in range(1, 160):
            term_c *= square / ((2*n-1)*(2*n))
            term_s *= square / ((2*n)*(2*n+1))
            cosine += term_c
            sine += term_s
            if max(abs(term_c), abs(term_s)) < Decimal('1e-65'):
                return +cosine, +sine
        raise ArithmeticError('trigonometric series did not converge')


def vertices(p, origin=(ZERO, ZERO)):
    c, s = axes(p['angle'])
    x, y = decimal(p['x'])-origin[0], decimal(p['y'])-origin[1]
    w, l = decimal(p['width'])/2, decimal(p['length'])/2
    return [(x+c*u-s*v, y+s*u+c*v) for u, v in
            [(-w, -l), (w, -l), (w, l), (-w, l)]]


def walls(p, box, gap):
    with localcontext() as context:
        context.prec = PRECISION
        e, margin = epsilon(p), decimal(gap)
        xy = all(margin-e <= x <= decimal(box['width'])-margin+e and
                 margin-e <= y <= decimal(box['length'])-margin+e
                 for x, y in vertices(p))
        z = decimal(p['z'])
        return xy, z >= -e and z+decimal(p['height']) <= decimal(box['height'])+e


def pair_error(p, q, gap):
    """Project vertices onto normalized face axes in a shared local frame.

    Z contact within the smaller epsilon removes the XY gap constraint. For
    overlapping heights a face axis must separate intervals by gap-epsilon.
    """
    with localcontext() as context:
        context.prec = PRECISION
        e = min(epsilon(p), epsilon(q))
        if (decimal(p['z'])+decimal(p['height']) <= decimal(q['z'])+e or
                decimal(q['z'])+decimal(q['height']) <= decimal(p['z'])+e):
            return None
        origin = decimal(p['x']), decimal(p['y'])
        a, b = vertices(p, origin), vertices(q, origin)
        separations = []
        for rectangle in (p, q):
            c, s = axes(rectangle['angle'])
            for ux, uy in ((c, s), (-s, c)):
                norm = (ux*ux+uy*uy).sqrt()
                pa = [(x*ux+y*uy)/norm for x, y in a]
                pb = [(x*ux+y*uy)/norm for x, y in b]
                separations.append(max(min(pb)-max(pa), min(pa)-max(pb)))
        separation = max(separations)
        if separation >= decimal(gap)-e:
            return None
        return 'overlapping products' if separation < -e else 'XY gap shortfall'


def clip_polygon(subject, clip):
    """Convex clipping supporting either float or Decimal coordinates."""
    result = list(subject)
    for a, b in zip(clip, clip[1:]+clip[:1]):
        points, result = result, []
        if not points:
            break
        for start, end in zip(points[-1:]+points[:-1], points):
            ds = (b[0]-a[0])*(start[1]-a[1])-(b[1]-a[1])*(start[0]-a[0])
            de = (b[0]-a[0])*(end[1]-a[1])-(b[1]-a[1])*(end[0]-a[0])
            if (ds >= 0) != (de >= 0):
                fraction = ds/(ds-de)
                result.append((start[0]+fraction*(end[0]-start[0]),
                               start[1]+fraction*(end[1]-start[1])))
            if de >= 0:
                result.append(end)
    return result


def full_support(p, placed):
    """Sweep clipped coplanar polygons in the candidate's physical local frame.

    Placed solids must be mutually disjoint, as in the public support contract.
    Face boundaries cannot exchange order between clipped polygon vertices.
    Slabs and interval gaps use linear epsilon, never uncovered area fractions.
    """
    with localcontext() as context:
        context.prec = PRECISION
        e = epsilon(p)
        if abs(decimal(p['z'])) < e:
            return True
        c, s = axes(p['angle'])
        half_w, half_l = decimal(p['width'])/2, decimal(p['length'])/2
        boundary = [(-half_w, -half_l), (half_w, -half_l),
                    (half_w, half_l), (-half_w, half_l)]
        faces = []
        origin = decimal(p['x']), decimal(p['y'])
        for q in placed:
            if q is p or abs(decimal(q['z'])+decimal(q['height'])-decimal(p['z'])) > e:
                continue
            local = [(x*c+y*s, -x*s+y*c) for x, y in vertices(q, origin)]
            face = clip_polygon(local, boundary)
            if face:
                faces.append(face)
        if not faces:
            return False
        xs = sorted({-half_w, half_w} | {x for face in faces for x, y in face})

        def section(x):
            intervals = []
            for face in faces:
                ys = []
                for (ax, ay), (bx, by) in zip(face, face[1:]+face[:1]):
                    if min(ax, bx) <= x <= max(ax, bx):
                        if ax == bx:
                            ys.extend((ay, by))
                        else:
                            ys.append(ay+(x-ax)*(by-ay)/(bx-ax))
                if ys:
                    intervals.append((min(ys), max(ys)))
            covered = -half_l
            for lo, hi in sorted(intervals):
                if lo > covered+e:
                    return False
                covered = max(covered, hi)
                if covered >= half_l-e:
                    return True
            return False

        return all(section(x) for left, right in zip(xs, xs[1:])
                   if right-left > e for x in (left, (left+right)/2, right))


def polygon_area(points):
    if len(points) < 3:
        return ZERO
    x, y = points[0]
    local = [(u-x, v-y) for u, v in points]
    return abs(sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(local, local[1:]+local[:1])))/2


def rests(p, placed):
    """Floor contact, or positive overlap with a coplanar top face.

    The overlap must exceed an epsilon-wide strip along the footprint perimeter,
    so edge or vertex contact alone never counts. No supported fraction is required.
    """
    with localcontext() as context:
        context.prec = PRECISION
        e = epsilon(p)
        if abs(decimal(p['z'])) < e:
            return True
        minimum = e*(decimal(p['width'])+decimal(p['length']))
        origin = decimal(p['x']), decimal(p['y'])
        footprint = vertices(p, origin)
        for q in placed:
            if q is p or abs(decimal(q['z'])+decimal(q['height'])-decimal(p['z'])) > e:
                continue
            if polygon_area(clip_polygon(vertices(q, origin), footprint)) > minimum:
                return True
        return False


def _hull(points):
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def turn(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])

    lower, upper = [], []
    for p in points:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]


def stable(p, placed):
    """Floor, or the footprint centre lies inside the convex hull of the positive-area
    contacts with coplanar top faces (a uniform rigid product does not tip).

    Contacts are clipped in the product's own physical frame; the centre may sit up
    to epsilon outside the hull to absorb serialization rounding.
    """
    with localcontext() as context:
        context.prec = PRECISION
        e = epsilon(p)
        if abs(decimal(p['z'])) < e:
            return True
        c, s = axes(p['angle'])
        half_w, half_l = decimal(p['width'])/2, decimal(p['length'])/2
        boundary = [(-half_w, -half_l), (half_w, -half_l), (half_w, half_l), (-half_w, half_l)]
        minimum = e*(decimal(p['width'])+decimal(p['length']))
        origin = decimal(p['x']), decimal(p['y'])
        points = []
        for q in placed:
            if q is p or abs(decimal(q['z'])+decimal(q['height'])-decimal(p['z'])) > e:
                continue
            local = [(x*c+y*s, -x*s+y*c) for x, y in vertices(q, origin)]
            face = clip_polygon(local, boundary)
            if polygon_area(face) > minimum:
                points.extend(face)
        hull = _hull(points)
        if len(hull) < 3:
            return False
        for (ax, ay), (bx, by) in zip(hull, hull[1:]+hull[:1]):
            length = ((bx-ax)**2+(by-ay)**2).sqrt()
            if (bx-ax)*(-ay)-(by-ay)*(-ax) < -e*length:
                return False
        return True

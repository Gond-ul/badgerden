"""
Rigid circles and plates in fixed point, fast enough to run several substeps a frame.

Positions are Q8 (1 px = 256). Bodies are circles; a plate is a row of circles
kept in a straight line by shape matching, so the same solver handles both.
Velocity is implicit (Verlet: position minus previous position), which keeps the
integer maths small and lets collisions push things around without extra state.
"""

from array import array

import micropython

Q = 256
DT = 1 / 120
CAPACITY = 40

# integrate() parameter slots
P_GX, P_GY, P_CX, P_CY, P_CENTRIFUGAL, P_EULER, P_CORIOLIS, P_DAMP = range(8)
# solve() settings slots
S_WIDTH, S_HEIGHT, S_REST, S_FRICTION = range(4)


@micropython.viper
def isqrt(n: int) -> int:
    if n <= 0:
        return 0
    result = 0
    bit = 1 << 28
    while bit > n:
        bit >>= 2
    while bit != 0:
        if n >= result + bit:
            n -= result + bit
            result = (result >> 1) + bit
        else:
            result >>= 1
        bit >>= 2
    return result


@micropython.viper
def integrate(n: int, X: ptr32, Y: ptr32, PX: ptr32, PY: ptr32, IM: ptr32, P: ptr32):
    gx = P[0]
    gy = P[1]
    cx = P[2]
    cy = P[3]
    centrifugal = P[4]
    euler = P[5]
    coriolis = P[6]
    damp = P[7]
    for i in range(n):
        if IM[i] == 0:
            continue
        x = X[i]
        y = Y[i]
        vx = ((x - PX[i]) * damp) >> 12
        vy = ((y - PY[i]) * damp) >> 12
        rx = x - cx
        ry = y - cy
        # apparent forces in the badge's rotating frame (screen x right, y down)
        ax = gx + ((centrifugal * rx + euler * ry + coriolis * vy) >> 16)
        ay = gy + ((centrifugal * ry - euler * rx - coriolis * vx) >> 16)
        PX[i] = x
        PY[i] = y
        X[i] = x + vx + ax
        Y[i] = y + vy + ay


@micropython.viper
def collide(n: int, X: ptr32, Y: ptr32, R: ptr32, IM: ptr32, G: ptr32, CX: ptr32, CY: ptr32) -> int:
    """Push overlapping circles apart. Returns the summed overlap, a rough impact measure."""
    overlap = 0
    for i in range(n):
        ri = R[i]
        gi = G[i]
        wi = IM[i]
        for j in range(i + 1, n):
            if gi != 0 and G[j] == gi:
                continue
            dx = X[j] - X[i]
            rr = ri + R[j]
            if dx >= rr or dx <= 0 - rr:
                continue
            dy = Y[j] - Y[i]
            if dy >= rr or dy <= 0 - rr:
                continue
            d2 = dx * dx + dy * dy
            if d2 >= rr * rr:
                continue
            wj = IM[j]
            ws = wi + wj
            if ws == 0:
                continue
            d = int(isqrt(d2))
            if d == 0:
                d = 1
                dx = 1
                dy = 0
            depth = rr - d
            nx = (dx << 8) // d
            ny = (dy << 8) // d
            mx = (nx * depth) >> 8
            my = (ny * depth) >> 8
            X[i] -= (mx * wi) // ws
            Y[i] -= (my * wi) // ws
            X[j] += (mx * wj) // ws
            Y[j] += (my * wj) // ws
            # contact normals point from the other body into this one (Q8)
            CX[i] = 0 - nx
            CY[i] = 0 - ny
            CX[j] = nx
            CY[j] = ny
            overlap += depth
    return overlap


@micropython.viper
def walls(n: int, X: ptr32, Y: ptr32, PX: ptr32, PY: ptr32, R: ptr32, IM: ptr32, S: ptr32,
          CX: ptr32, CY: ptr32) -> int:
    """Keep circles on screen, bouncing off the edges. Returns the summed impact speed."""
    width = S[0]
    height = S[1]
    rest = S[2]
    keep = S[3]
    impact = 0
    for i in range(n):
        if IM[i] == 0:
            continue
        r = R[i]
        x = X[i]
        y = Y[i]
        if x < r or x > width - r:
            vx = x - PX[i]
            wall = width - r
            normal = -256
            if x < r:
                wall = r
                normal = 256
            X[i] = wall
            speed = vx
            if speed < 0:
                speed = 0 - vx
            # only bounce real hits, so resting bodies don't buzz
            PX[i] = wall
            if speed > 96:
                PX[i] = wall + ((vx * rest) >> 8)
            PY[i] = y - (((y - PY[i]) * keep) >> 8)
            CX[i] = normal
            CY[i] = 0
            impact += speed
        if y < r or y > height - r:
            vy = y - PY[i]
            wall = height - r
            normal = -256
            if y < r:
                wall = r
                normal = 256
            Y[i] = wall
            speed = vy
            if speed < 0:
                speed = 0 - vy
            PY[i] = wall
            if speed > 96:
                PY[i] = wall + ((vy * rest) >> 8)
            PX[i] = X[i] - (((X[i] - PX[i]) * keep) >> 8)
            CX[i] = 0
            CY[i] = normal
            impact += speed
    return impact


@micropython.viper
def rigidify(plates: ptr32, count: int, X: ptr32, Y: ptr32, O: ptr32, U: ptr32):
    """Snap each plate's circles back onto a straight line through their centroid."""
    for p in range(count):
        start = plates[p * 2]
        m = plates[p * 2 + 1]
        sx = 0
        sy = 0
        for i in range(start, start + m):
            sx += X[i]
            sy += Y[i]
        cx = sx // m
        cy = sy // m
        ax = 0
        ay = 0
        for i in range(start, start + m):
            o = O[i] >> 4
            ax += o * ((X[i] - cx) >> 4)
            ay += o * ((Y[i] - cy) >> 4)
        while ax > 23000 or ax < -23000 or ay > 23000 or ay < -23000:
            ax >>= 1
            ay >>= 1
        length = int(isqrt(ax * ax + ay * ay))
        if length == 0:
            continue
        ux = (ax << 12) // length
        uy = (ay << 12) // length
        for i in range(start, start + m):
            o = O[i]
            X[i] = cx + ((o * ux) >> 12)
            Y[i] = cy + ((o * uy) >> 12)
        U[p * 2] = ux
        U[p * 2 + 1] = uy


class World:
    def __init__(self, width, height, restitution=0.42, friction=0.06, drag=0.4):
        self.n = 0
        self.width = width
        self.height = height
        zeros = [0] * CAPACITY
        self.X = array("i", zeros)
        self.Y = array("i", zeros)
        self.PX = array("i", zeros)
        self.PY = array("i", zeros)
        self.R = array("i", zeros)
        self.IM = array("i", zeros)
        self.G = array("i", zeros)
        self.O = array("i", zeros)
        self.CX = array("i", zeros)
        self.CY = array("i", zeros)
        self.radius = [0.0] * CAPACITY
        self.plates = []
        self.PL = array("i", [0] * 16)
        self.PU = array("i", [4096, 0] * 8)
        self.P = array("i", [0] * 8)
        self.S = array("i", [int(width * Q), int(height * Q), int(restitution * 256), int((1 - friction) * 256)])
        self.damp = int(4096 * (1 - drag * DT))
        self.spare = 0.0
        self.impact = 0
        self.overlap = 0
        self.iterations = 2

    def add_circle(self, x, y, r, mass=1.0, group=0, offset=0.0):
        i = self.n
        self.n += 1
        self.X[i] = self.PX[i] = int(x * Q)
        self.Y[i] = self.PY[i] = int(y * Q)
        self.R[i] = int(r * Q)
        self.radius[i] = r
        self.IM[i] = int(256 / mass) if mass else 0
        self.G[i] = group
        self.O[i] = int(offset * Q)
        return i

    def add_plate(self, x, y, length, thickness, mass=2.0):
        """A rigid bar made of overlapping circles. Returns (plate id, first circle, count)."""
        r = thickness / 2
        reach = max(0.0, length / 2 - r)
        count = max(2, int(reach * 2 / (r * 1.1)) + 1)
        plate = len(self.plates)
        start = self.n
        for k in range(count):
            offset = -reach + 2 * reach * k / (count - 1)
            self.add_circle(x + offset, y, r, mass / count, plate + 1, offset)
        self.plates.append((start, count))
        self.PL[plate * 2] = start
        self.PL[plate * 2 + 1] = count
        return plate, start, count

    def position(self, i):
        return self.X[i] / Q, self.Y[i] / Q

    def velocity(self, i):
        """px/s, from the last substep."""
        return (self.X[i] - self.PX[i]) / (Q * DT), (self.Y[i] - self.PY[i]) / (Q * DT)

    def plate_axis(self, plate):
        return self.PU[plate * 2] / 4096, self.PU[plate * 2 + 1] / 4096

    def plate_centre(self, plate):
        start, count = self.plates[plate]
        sx = sy = 0
        for i in range(start, start + count):
            sx += self.X[i]
            sy += self.Y[i]
        return sx / (count * Q), sy / (count * Q)

    def kick(self, i, vx, vy):
        """Add velocity (px/s) to circle i."""
        self.PX[i] -= int(vx * DT * Q)
        self.PY[i] -= int(vy * DT * Q)

    def kick_plate(self, plate, vx, vy, spin=0.0):
        start, count = self.plates[plate]
        ux, uy = self.plate_axis(plate)
        for i in range(start, start + count):
            o = self.O[i] / Q
            self.kick(i, vx - uy * o * spin, vy + ux * o * spin)

    def step(self, elapsed, ax, ay, spin=0.0, spin_rate=0.0):
        """Advance by elapsed seconds. ax, ay: px/s^2 felt by everything; spin: badge
        rotation rad/s (clockwise +); spin_rate: its rate of change, rad/s^2."""
        self.spare = min(self.spare + elapsed, DT * 4)
        P = self.P
        P[P_GX] = int(ax * DT * DT * Q)
        P[P_GY] = int(ay * DT * DT * Q)
        P[P_CX] = int(self.width * Q / 2)
        P[P_CY] = int(self.height * Q / 2)
        P[P_CENTRIFUGAL] = int(spin * spin * DT * DT * 65536)
        P[P_EULER] = int(spin_rate * DT * DT * 65536)
        P[P_CORIOLIS] = int(2 * spin * DT * 65536)
        P[P_DAMP] = self.damp
        impact = 0
        overlap = 0
        n = self.n
        # contact normals are rebuilt by this step; rolling reads them afterwards
        for i in range(n):
            self.CX[i] = 0
            self.CY[i] = 0
        while self.spare >= DT:
            self.spare -= DT
            integrate(n, self.X, self.Y, self.PX, self.PY, self.IM, P)
            for _ in range(self.iterations):
                overlap += collide(n, self.X, self.Y, self.R, self.IM, self.G, self.CX, self.CY)
                impact += walls(n, self.X, self.Y, self.PX, self.PY, self.R, self.IM, self.S, self.CX, self.CY)
                rigidify(self.PL, len(self.plates), self.X, self.Y, self.O, self.PU)
        self.impact = impact / Q
        self.overlap = overlap / Q

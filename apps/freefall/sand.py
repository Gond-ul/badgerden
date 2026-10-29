"""
Contribution sand: one grain per contribution, on a 64x48 grid of 5 px cells.

Grains fall one cell per step in the gravity direction, sliding diagonally when
blocked, so they pile up at the angle of repose and pour when the badge tilts.
Bodies are obstacles: grains under them are shoved aside and can't flow in.
Drawn straight into the RGB565 framebuffer as 4x4 squares with a 1 px gap, like
the contribution graph.

The grid has a one-cell border that is always blocked, so moves need no bounds
checks: a cell's neighbour is just its index plus an offset.
"""

import math
from array import array

import micropython

COLS = 64
ROWS = 48
CELL = 5
WIDE = COLS + 2
SIZE = WIDE * (ROWS + 2)
# the eight neighbours clockwise from +x, as index offsets in the padded grid
OFFSETS = array("i", (1, WIDE + 1, WIDE, WIDE - 1, -1, -WIDE - 1, -WIDE, -WIDE + 1))
STEP_X = (1, 1, 0, -1, -1, -1, 0, 1)
STEP_Y = (0, 1, 1, 1, 0, -1, -1, -1)
BORDER = bytes(1 if x in (0, WIDE - 1) or y in (0, ROWS + 1) else 0 for y in range(ROWS + 2) for x in range(WIDE))
# one cycle of a slow pulse for the stars' twinkle
WAVE = bytes(int(140 + 115 * math.sin(i * math.pi / 32)) for i in range(64))


@micropython.viper
def _rand(s: int) -> int:
    s ^= s << 13
    s ^= (s >> 17) & 0x7FFF
    s ^= s << 5
    return s


@micropython.viper
def flow(grid: ptr8, blocked: ptr8, offsets: ptr32, base: int, alt: int, chance: int,
         seed: int, sweep_x: int, sweep_y: int) -> int:
    """One step of falling. base/alt are direction indices; alt is used with chance/256.
    sweep_x/sweep_y (+1/-1) visit downstream cells first so nothing moves twice."""
    s = seed | 1
    moved = 0
    for yy in range(48):
        y = yy + 1
        if sweep_y < 0:
            y = 48 - yy
        row = y * 66
        for xx in range(64):
            x = xx + 1
            if sweep_x < 0:
                x = 64 - xx
            here = row + x
            if grid[here] == 0:
                continue
            s ^= s << 13
            s ^= (s >> 17) & 0x7FFF
            s ^= s << 5
            d = base
            if (s & 255) < chance:
                d = alt
            t = here + offsets[d]
            if grid[t] == 0 and blocked[t] == 0:
                grid[t] = grid[here]
                grid[here] = 0
                moved += 1
                continue
            first = offsets[(d + 1) & 7]
            second = offsets[(d + 7) & 7]
            if s & 256:
                first = offsets[(d + 7) & 7]
                second = offsets[(d + 1) & 7]
            t = here + first
            if grid[t] == 0 and blocked[t] == 0:
                grid[t] = grid[here]
                grid[here] = 0
                moved += 1
                continue
            t = here + second
            if grid[t] == 0 and blocked[t] == 0:
                grid[t] = grid[here]
                grid[here] = 0
                moved += 1
    return moved


@micropython.viper
def jiggle(grid: ptr8, blocked: ptr8, offsets: ptr32, chance: int, seed: int) -> int:
    """Random walk for zero-g, heat and shaking: each grain moves with chance/256."""
    s = seed | 1
    moved = 0
    for here in range(3300):
        if grid[here] == 0:
            continue
        s ^= s << 13
        s ^= (s >> 17) & 0x7FFF
        s ^= s << 5
        if (s & 255) >= chance:
            continue
        t = here + offsets[(s >> 8) & 7]
        if grid[t] == 0 and blocked[t] == 0:
            grid[t] = grid[here]
            grid[here] = 0
            moved += 1
    return moved


@micropython.viper
def mark(grid: ptr8, blocked: ptr8, bodies: ptr32, count: int, shoved: ptr32) -> int:
    """Block the cells under each body (x, y, r in px) and shove any grains there
    outward. shoved[b] gets how many grains body b pushed. blocked must arrive
    holding just the border."""
    total = 0
    for b in range(count):
        bx = bodies[b * 3]
        by = bodies[b * 3 + 1]
        br = bodies[b * 3 + 2]
        reach = br + 2
        # x // 5 via multiply-shift (exact for the screen's range)
        x0 = ((bx - reach) * 13108) >> 16
        x1 = ((bx + reach) * 13108) >> 16
        y0 = ((by - reach) * 13108) >> 16
        y1 = ((by + reach) * 13108) >> 16
        if bx - reach < 0:
            x0 = 0
        if by - reach < 0:
            y0 = 0
        if x1 > 63:
            x1 = 63
        if y1 > 47:
            y1 = 47
        pushed = 0
        for cy in range(y0, y1 + 1):
            for cx in range(x0, x1 + 1):
                ox = cx * 5 + 2 - bx
                oy = cy * 5 + 2 - by
                if ox * ox + oy * oy > reach * reach:
                    continue
                here = (cy + 1) * 66 + cx + 1
                blocked[here] = 1
                if grid[here] == 0:
                    continue
                # step away from the body's centre until a free cell outside it turns up
                sx = 0
                sy = 0
                ax = ox
                if ax < 0:
                    ax = 0 - ox
                ay = oy
                if ay < 0:
                    ay = 0 - oy
                if ax * 2 >= ay:
                    sx = 1
                    if ox < 0:
                        sx = -1
                if ay * 2 >= ax:
                    sy = 1
                    if oy < 0:
                        sy = -1
                if sx == 0 and sy == 0:
                    sy = -1
                tx = cx
                ty = cy
                for step in range(14):
                    tx += sx
                    ty += sy
                    if tx < 0 or tx >= 64 or ty < 0 or ty >= 48:
                        break
                    px = tx * 5 + 2 - bx
                    py = ty * 5 + 2 - by
                    if px * px + py * py <= reach * reach:
                        continue
                    t = (ty + 1) * 66 + tx + 1
                    if grid[t] == 0 and blocked[t] == 0:
                        grid[t] = grid[here]
                        grid[here] = 0
                        pushed += 1
                        break
        shoved[b] = pushed
        total += pushed
    return total


@micropython.viper
def draw(frame: ptr16, grid: ptr8, palette: ptr16):
    """Paint every grain as a 4x4 square into a 320-wide RGB565 framebuffer."""
    for cy in range(48):
        row = (cy + 1) * 66 + 1
        top = cy * 5 * 320
        for cx in range(64):
            v = int(grid[row + cx])
            if v == 0:
                continue
            colour = palette[v]
            p = top + cx * 5
            for j in range(4):
                frame[p] = colour
                frame[p + 1] = colour
                frame[p + 2] = colour
                frame[p + 3] = colour
                p += 320


@micropython.viper
def stars(frame: ptr16, xs: ptr16, ys: ptr16, sizes: ptr8, phases: ptr8, n: int, wave: ptr8,
          tick: int, level: int, shift_x: int, shift_y: int):
    """Twinkling stars, written straight into the framebuffer. level 0-256 is how dark it is."""
    for i in range(n):
        b = (int(wave[(int(phases[i]) + tick) & 63]) * level) >> 8
        if b < 12:
            continue
        r = b >> 3
        g = b >> 2
        blue = (b + 40) >> 3
        if blue > 31:
            blue = 31
        colour = (r << 11) | (g << 5) | blue
        size = int(sizes[i])
        x = int(xs[i]) + shift_x * size
        y = int(ys[i]) + shift_y * size
        while x < 0:
            x += 320
        while x >= 319:
            x -= 319
        while y < 0:
            y += 240
        while y >= 239:
            y -= 239
        p = y * 320 + x
        frame[p] = colour
        if size > 1:
            frame[p + 1] = colour
            frame[p + 320] = colour
            frame[p + 321] = colour


def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


class Sand:
    def __init__(self, palette):
        self.grid = bytearray(SIZE)
        self.blocked = bytearray(BORDER)
        self.palette = array("H", [0] + [rgb565(*c) for c in palette])
        self.queue = []
        self.next = 0
        self.seed = 12345
        self.count = 0
        self.flip = 1
        self.bodies = array("i", [0] * 60)
        self.shoved = array("i", [0] * 20)

    def pour(self, levels):
        """Queue grains (each a level 1-4) to pour in."""
        self.queue = levels
        self.next = 0

    @property
    def waiting(self):
        return len(self.queue) - self.next

    def clear(self):
        self.grid[:] = bytes(SIZE)
        self.count = 0

    def spawn(self, per_frame, up_x, up_y):
        """Drop queued grains in along the edge gravity points away from."""
        grid = self.grid
        for _ in range(per_frame):
            if self.next >= len(self.queue):
                return
            self.seed = _rand(self.seed)
            spread = (self.seed >> 3) % 40 - 20
            # start near the middle of the edge opposite gravity
            cx = int(COLS / 2 + up_x * (COLS / 2 - 1) + spread * abs(up_y))
            cy = int(ROWS / 2 + up_y * (ROWS / 2 - 1) + spread * abs(up_x) * 0.6)
            cx = min(COLS - 1, max(0, cx))
            cy = min(ROWS - 1, max(0, cy))
            i = (cy + 1) * WIDE + cx + 1
            if grid[i] or self.blocked[i]:
                return
            grid[i] = self.queue[self.next]
            self.next += 1
            self.count += 1

    def obstacles(self, circles):
        """circles: list of (x, y, r) in px. Returns grains shoved per body."""
        bodies = self.bodies
        n = min(len(circles), 20)
        for k in range(n):
            x, y, r = circles[k]
            bodies[k * 3] = int(x)
            bodies[k * 3 + 1] = int(y)
            bodies[k * 3 + 2] = int(r)
        self.blocked[:] = BORDER
        mark(self.grid, self.blocked, bodies, n, self.shoved)
        return self.shoved

    def fall(self, gx, gy, steps):
        """gx, gy: gravity direction on screen (any length)."""
        octant = (math.atan2(gy, gx) / (math.pi / 4)) % 8
        base = int(octant) % 8
        alt = (base + 1) % 8
        chance = int((octant - int(octant)) * 256)
        lead = base if chance < 128 else alt
        sweep_x = -1 if STEP_X[lead] > 0 else 1
        sweep_y = -1 if STEP_Y[lead] > 0 else 1
        if STEP_X[lead] == 0:
            sweep_x = self.flip
        if STEP_Y[lead] == 0:
            sweep_y = self.flip
        self.flip = -self.flip
        moved = 0
        for _ in range(steps):
            self.seed = _rand(self.seed)
            moved += flow(self.grid, self.blocked, OFFSETS, base, alt, chance, self.seed, sweep_x, sweep_y)
        return moved

    def stir(self, chance):
        self.seed = _rand(self.seed)
        return jiggle(self.grid, self.blocked, OFFSETS, int(chance), self.seed)

    def draw(self, frame):
        draw(frame, self.grid, self.palette)

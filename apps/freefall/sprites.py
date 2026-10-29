"""
Round things and lettering pre-rendered at a ring of angles, so a spinning avatar,
coin or name costs a few blits a frame instead of vector fills. Angles render the
first time they're needed, so start-up is quick and memory only goes on the
angles actually used. The badge's runtime globals (image, shape, brush, mat3,
vec2) are bound in by the app at start-up.
"""

import math

TAU = math.pi * 2


class Spinner:
    def __init__(self, size, steps, paint):
        self.size = size
        self.half = size // 2
        self.steps = steps
        self.paint = paint
        self.frames = [None] * steps

    def frame(self, angle):
        k = int(round(angle / TAU * self.steps)) % self.steps
        frame = self.frames[k]
        if frame is None:
            frame = image(self.size, self.size)
            frame.antialias = image.X2
            self.paint(frame, k * 360 / self.steps)
            self.frames[k] = frame
        return frame

    def draw(self, target, x, y, angle):
        target.blit(self.frame(angle), vec2(int(x) - self.half, int(y) - self.half))


def centred_text(target, text, typeface, size, cx, cy, turn):
    target.font = typeface
    w, h = target.measure_text(text, font_size=size)
    target.text(text, cx - w / 2, cy - h / 2, size, transform=turn)


def avatar(picture, radius, ring, steps=48):
    size = int(radius * 2 + 2)
    c = size / 2

    def paint(frame, degrees):
        frame.pen = ring
        frame.shape(shape.circle(c, c, radius))
        inner = radius - 3
        scale = inner * 2 / picture.width
        place = mat3().translate(c, c).rotate(degrees).scale(scale, scale).translate(-picture.width / 2, -picture.height / 2)
        frame.pen = brush.image(picture, place)
        frame.shape(shape.circle(c, c, inner))

    return Spinner(size, steps, paint)


def initials(name, radius, fill, ring, ink, typeface, steps=48):
    """Stand-in for the avatar before it has downloaded."""
    letters = "".join(word[0] for word in name.split()[:2]).upper() or "?"
    size = int(radius * 2 + 2)
    c = size / 2

    def paint(frame, degrees):
        frame.pen = ring
        frame.shape(shape.circle(c, c, radius))
        frame.pen = fill
        frame.shape(shape.circle(c, c, radius - 3))
        frame.pen = ink
        turn = mat3().translate(c, c).rotate(degrees).translate(-c, -c)
        centred_text(frame, letters, typeface, int(radius * 0.8), c, c, turn)

    return Spinner(size, steps, paint)


def coin(radius, value, label, fill, ring, ink, faint, typeface, steps=48):
    size = int(radius * 2 + 2)
    c = size / 2
    value_size = radius * 0.78
    if len(value) > 3:
        value_size = radius * 2.4 / len(value)
    label_size = max(9, radius * 0.36)

    def paint(frame, degrees):
        frame.pen = ring
        frame.shape(shape.circle(c, c, radius))
        frame.pen = fill
        frame.shape(shape.circle(c, c, radius - 2.5))
        turn = mat3().translate(c, c).rotate(degrees).translate(-c, -c)
        # a notch on the rim makes the roll visible even when the face is upright
        frame.pen = faint
        notch = shape.circle(c, c + radius - 6, 1.6)
        notch.transform = turn
        frame.shape(notch)
        frame.pen = ink
        centred_text(frame, value, typeface, value_size, c, c - radius * 0.12, turn)
        frame.pen = faint
        centred_text(frame, label, typeface, label_size, c, c + radius * 0.42, turn)

    return Spinner(size, steps, paint)


class Lettering:
    """A word laid along a line, one pre-rotated sprite per letter."""

    def __init__(self, text, typeface, size, ink, steps=60):
        scratch = image(4, 4)
        scratch.font = typeface
        self.width, line = scratch.measure_text(text, font_size=size)
        cell = int(size * 1.6) + 2
        c = cell / 2
        self.letters = []
        glyphs = {}
        left = -self.width / 2
        for i, ch in enumerate(text):
            start = scratch.measure_text(text[:i], font_size=size)[0] if i else 0
            end = scratch.measure_text(text[:i + 1], font_size=size)[0]
            if ch != " " and ch not in glyphs:
                advance = scratch.measure_text(ch, font_size=size)[0]

                def paint(frame, degrees, ch=ch, advance=advance):
                    frame.font = typeface
                    frame.pen = ink
                    turn = mat3().translate(c, c).rotate(degrees).translate(-c, -c)
                    frame.text(ch, c - advance / 2, c - line / 2, size, transform=turn)

                glyphs[ch] = Spinner(cell, steps, paint)
            if ch != " ":
                self.letters.append((glyphs[ch], left + (start + end) / 2))
        self.half = cell // 2

    def draw(self, target, cx, cy, angle):
        ca = math.cos(angle)
        sa = math.sin(angle)
        half = self.half
        for spinner, offset in self.letters:
            frame = spinner.frame(angle)
            target.blit(frame, vec2(int(cx + ca * offset) - half, int(cy + sa * offset) - half))

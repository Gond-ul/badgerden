"""
Hello Den: the smallest useful badge app, and a template for your own.

Installed from Badgerden. Copy this folder, rename it, edit app.json and push.

Controls:
* Select = Change colour
* Back = Return to the launcher
"""

import math

badge.mode(HIRES)
screen.antialias = image.X2

CX, CY = screen.width / 2, screen.height / 2

COLOURS = [
    color.rgb(95, 237, 131),
    color.rgb(22, 143, 251),
    color.rgb(247, 54, 120),
    color.rgb(255, 196, 70),
]
BACKGROUND = color.rgb(16, 20, 17)
DIM = color.rgb(144, 150, 146)

colour = 0


def centred(text, y, typeface, pen):
    screen.font = typeface
    screen.pen = pen
    width, _ = screen.measure_text(text)
    screen.text(text, CX - width / 2, y)


def update():
    global colour
    if badge.pressed(BUTTON_SELECT):
        colour = (colour + 1) % len(COLOURS)
    if badge.pressed(BUTTON_BACK):
        reset()

    screen.pen = BACKGROUND
    screen.clear()

    t = badge.ticks / 1000
    for i in range(12):
        angle = t + i * math.pi / 6
        screen.pen = COLOURS[(colour + i) % len(COLOURS)]
        screen.shape(shape.circle(CX + math.cos(angle) * 70, CY - 10 + math.sin(angle) * 50, 4))

    centred("hello from the den", CY - 22, font.ziplock, COLOURS[colour])
    centred("installed over wi-fi", CY + 2, font.corset, DIM)
    centred("select: colour   back: menu", screen.height - 24, font.corset, DIM)


run(update)

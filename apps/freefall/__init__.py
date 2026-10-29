"""
Freefall: your GitHub profile in a box that knows which way is down.

Your avatar, name, handle, repo count and contributions are physical objects that
fall, roll and tumble with the real gravity the badge feels. Every contribution
from the last year is a grain of sand coloured by its day.

Sensors:
* Accelerometer = which way is down, shaking sloshes everything, flat = zero-g
* Gyroscope = spin the badge to swirl things around
* Taps on the case knock things over; double tap to launch them
* Touch d-pad = blow wind in that direction
* Light sensor = day and night; temperature = how restless the sand is in zero-g
* Battery = the battery ball; Wi-Fi strength in the sensor panel

Controls:
* Select = jump
* Up / Down buttons = planet (Earth, Moon, Mars, Jupiter, space)
* Menu = sensor panel
* Back = launcher
"""

import gc
import math
import os
import random
import sys
import time
from array import array

try:
    APP_DIR = __file__.rsplit("/", 1)[0]
except NameError:
    APP_DIR = "/system/apps/freefall"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

import missing_details

import profile
import sprites
from sand import WAVE, Sand, stars
from sensors import Sensors
from world import World

try:
    import secrets
except ImportError:
    secrets = None

# a test harness can drive the app (fake motion, screenshots) by registering this module
HOOK = getattr(sys.modules.get("freefall_hook"), "hook", None)
# with this file present, timings go to the USB console every few seconds
try:
    os.stat("/state/freefall_debug")
    DEBUG = True
except OSError:
    DEBUG = False


badge.mode(HIRES | VSYNC)

# the runtime's drawing names resolve here but not inside imported modules, so hand
# them over. screen is passed at draw time instead: changing mode replaces it.
for module in (sprites, profile):
    module.image = image
    module.shape = shape
    module.brush = brush
    module.mat3 = mat3
    module.vec2 = vec2
    module.rect = rect
    module.color = color
    module.font = font

previous_clear = badge.default_clear
# the sky is painted every frame anyway, so skip the firmware's own clear
badge.default_clear = None
previous_autorotate = badge.autorotate()
# the scene does its own orientation: the firmware flipping the screen would fight it
badge.autorotate(False)
screen.antialias = image.X2

W, H = screen.width, screen.height
TAU = math.pi * 2

# how hard 1 g pulls, in px/s^2: slower than life so you can watch things fall
G_PX = 1400.0
PLANETS = (("earth", 1.0), ("moon", 0.165), ("mars", 0.38), ("jupiter", 2.53), ("space", 0.0))
ROTATION_GAIN = 0.6
WIND = 2200.0
JUMP = 520.0
RIGHTING = 60.0
ZERO_G = 0.15

NIGHT_SKY = (13, 17, 23)
DAY_SKY = (30, 48, 76)
WHITE = color.rgb(240, 246, 252)
INK = color.rgb(13, 17, 23)
MUTED = color.rgb(139, 148, 158)
FAINT = color.rgb(110, 118, 129)
EDGE = color.rgb(48, 54, 61)
GREEN = color.rgb(63, 185, 80)
GREEN_DARK = color.rgb(35, 134, 54)
BLUE = color.rgb(88, 166, 255)
COIN = color.rgb(22, 27, 34)
AMBER = color.rgb(210, 153, 34)
RED = color.rgb(248, 81, 73)
SAND_GREENS = ((14, 68, 41), (0, 109, 50), (38, 166, 65), (57, 211, 83))

AVATAR_R = 34
REPO_R = 25
CONTRIB_R = 31
BATTERY_R = 15
NAME_SIZE = 19
HANDLE_SIZE = 16
NAME_THICK = 30
HANDLE_THICK = 26

mona = font.load("/system/assets/fonts/MonaSans-Medium.af")
small = font.sins
heading = font.ziplock


def setting(key):
    return str(getattr(secrets, key, "") or "").strip()


def mix(a, b, t):
    return color.rgb(*(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))


def wrap(angle):
    return (angle + math.pi) % TAU - math.pi


def short(number):
    if number is None:
        return "?"
    if number >= 10000:
        return "%.1fk" % (number / 1000)
    return str(number)


def loading(message):
    screen.pen = color.rgb(*NIGHT_SKY)
    screen.clear()
    screen.font = heading
    screen.pen = GREEN
    screen.text("freefall", rect(0, 92, W, 30), align=image.CENTER)
    screen.font = small
    screen.pen = MUTED
    screen.text(message, rect(0, 128, W, 20), align=image.CENTER)
    badge.update()


loading("reading your profile")

MISSING_WIFI = missing_details.missing("WIFI_SSID")
wifi = None
if not MISSING_WIFI:
    import wifi
    wifi.connect(timeout=10, retries=100000)

me = profile.Profile(setting("GITHUB_USERNAME"), setting("CONTACT_NAME"), wifi)
sensors = Sensors(badge)
sand = Sand(SAND_GREENS)


def avatar_fingerprint():
    """Same picture under a new file name shouldn't mean redrawing everything."""
    if not me.avatar:
        return None
    try:
        import binascii
        with open(me.avatar, "rb") as f:
            return binascii.crc32(f.read())
    except OSError:
        return None


class Scene:
    """Bodies, their spin and their artwork, rebuilt when the profile's text changes."""

    def __init__(self):
        self.name = None
        self.handle = None
        self.world = None
        self.avatar_art = None
        self.repo_art = None
        self.contrib_art = None
        self.art_for = None

    def build(self):
        name = me.name or "your name"
        handle = "@" + (me.handle or "your-handle")
        if self.world is not None and (name, handle) == (self.name, self.handle):
            return
        self.name, self.handle = name, handle
        world = World(W, H)
        self.avatar = world.add_circle(70, 70, AVATAR_R, mass=4)
        self.repo = world.add_circle(160, 44, REPO_R, mass=2)
        self.contrib = world.add_circle(250, 66, CONTRIB_R, mass=2.6)
        self.battery = world.add_circle(125, 104, BATTERY_R, mass=1)
        self.name_text = sprites.Lettering(name, mona, NAME_SIZE, INK)
        self.handle_text = sprites.Lettering(handle, mona, HANDLE_SIZE, WHITE)
        self.name_len = min(W - 20, self.name_text.width + 28)
        self.handle_len = min(W - 20, self.handle_text.width + 24)
        self.name_plate = world.add_plate(165, 140, self.name_len, NAME_THICK, mass=3)[0]
        self.handle_plate = world.add_plate(150, 182, self.handle_len, HANDLE_THICK, mass=2)[0]
        self.round = (self.avatar, self.repo, self.contrib, self.battery)
        self.radius = (AVATAR_R, REPO_R, CONTRIB_R, BATTERY_R)
        self.angle = [0.0] * 4
        self.rate = [0.0] * 4
        self.flipped = [False, False]
        self.world = world

    def paint(self):
        """Set up the spinning artwork for the current profile."""
        key = (avatar_fingerprint(), me.repos, me.contributions, me.name)
        if key == self.art_for:
            return
        self.art_for = key
        self.avatar_art = self.repo_art = self.contrib_art = None
        gc.collect()
        picture = None
        if me.avatar:
            try:
                size = (AVATAR_R - 3) * 2
                picture = image.load(me.avatar, size, size)
            except (OSError, ValueError, RuntimeError) as error:
                print("freefall: avatar", error)
        if picture is not None:
            self.avatar_art = sprites.avatar(picture, AVATAR_R, WHITE)
        else:
            self.avatar_art = sprites.initials(me.name or "?", AVATAR_R, GREEN_DARK, WHITE, WHITE, mona)
        self.repo_art = sprites.coin(REPO_R, short(me.repos), "repos", COIN, BLUE, WHITE, MUTED, mona)
        self.contrib_art = sprites.coin(CONTRIB_R, short(me.contributions), "contribs", COIN, GREEN, WHITE, MUTED, mona)
        gc.collect()


scene = Scene()
loading("building the room")
scene.build()
scene.paint()


def pour():
    levels, per = me.grains()
    sand.clear()
    sand.pour(levels)
    return per


grain_value = pour()
seen_version = me.version

STAR_COUNT = 48
star_x = array("H", [random.randint(0, W - 2) for _ in range(STAR_COUNT)])
star_y = array("H", [random.randint(0, H - 2) for _ in range(STAR_COUNT)])
star_size = bytes(random.choice((1, 1, 1, 2)) for _ in range(STAR_COUNT))
star_phase = bytes(random.randint(0, 63) for _ in range(STAR_COUNT))

planet = 0
panel = False
banner = None
banner_at = 0
glow = 0.0
lit = 0.0
night = 1.0
shake_until = 0
frame = 0
timings = {}
totals = {}
totals_since = [0]


def say(text):
    global banner, banner_at
    banner = text
    banner_at = badge.ticks


def up_direction():
    """Unit vector pointing away from gravity on screen, or None in zero-g."""
    pull = sensors.pull
    if pull < ZERO_G:
        return None
    return -sensors.gx / pull, -sensors.gy / pull


def launch(strength, spread=0.6):
    """Throw everything against gravity (or anywhere, when there isn't any)."""
    world = scene.world
    up = up_direction()
    for i in scene.round:
        ux, uy = up if up else (math.cos(random.random() * TAU), math.sin(random.random() * TAU))
        speed = strength * (0.75 + random.random() * 0.5)
        side = (random.random() - 0.5) * spread
        world.kick(i, (ux - uy * side) * speed, (uy + ux * side) * speed)
    for k in range(2):
        plate = (scene.name_plate, scene.handle_plate)[k]
        ux, uy = up if up else (0.0, -1.0)
        world.kick_plate(plate, ux * strength * 0.8, uy * strength * 0.8, (random.random() - 0.5) * 6)
    for k in range(4):
        scene.rate[k] += (random.random() - 0.5) * 16


def handle_input():
    global planet, panel
    if badge.pressed(BUTTON_BACK):
        on_exit()
        reset()
    if badge.pressed(BUTTON_MENU):
        panel = not panel
    if badge.pressed(BUTTON_SELECT):
        launch(JUMP)
    # the touch d-pad blows wind, so only the physical buttons change planet
    if badge.pressed(BUTTON_UP) and not badge.touched(BUTTON_UP):
        planet = (planet + 1) % len(PLANETS)
        say(PLANETS[planet][0])
    if badge.pressed(BUTTON_DOWN) and not badge.touched(BUTTON_DOWN):
        planet = (planet - 1) % len(PLANETS)
        say(PLANETS[planet][0])
    for event in sensors.events:
        if event == "single_tap":
            launch(JUMP * 0.45, 2.0)
            say("tap!")
        elif event == "double_tap":
            launch(JUMP * 1.3)
            say("double tap!")
        elif event == "freefall":
            say("free fall!")


def turn_round_bodies(dt):
    """Roll the round things, and right them like weighted toys when gravity allows."""
    world = scene.world
    up = up_direction()
    up_angle = math.atan2(up[0], -up[1]) if up else None
    pull = sensors.pull * PLANETS[planet][1]
    spin = sensors.spin * ROTATION_GAIN
    for k in range(4):
        i = scene.round[k]
        rate = scene.rate[k]
        nx, ny = world.CX[i], world.CY[i]
        if nx or ny:
            vx, vy = world.velocity(i)
            roll = (vx * -ny + vy * nx) / (256 * scene.radius[k])
            rate += (roll - rate) * min(1.0, dt * 10)
        if up_angle is not None:
            rate -= RIGHTING * math.sin(wrap(scene.angle[k] - up_angle)) * pull * dt
            rate -= 3.0 * rate * dt
        else:
            # nothing to right it: it keeps turning while the badge turns under it
            rate -= 0.3 * (rate + spin) * dt
        rate -= sensors.spin_rate * ROTATION_GAIN * dt
        scene.rate[k] = rate
        scene.angle[k] = wrap(scene.angle[k] + rate * dt)


def step_sand(ax, ay):
    world = scene.world
    circles = [(world.X[i] >> 8, world.Y[i] >> 8, world.radius[i]) for i in range(world.n)]
    shoved = sand.obstacles(circles)
    # wading through sand slows things down
    for i in range(world.n):
        if shoved[i]:
            keep = max(0.55, 1 - shoved[i] * 0.025)
            world.PX[i] = world.X[i] - int((world.X[i] - world.PX[i]) * keep)
            world.PY[i] = world.Y[i] - int((world.Y[i] - world.PY[i]) * keep)
    strength = math.sqrt(ax * ax + ay * ay) / G_PX
    if strength > ZERO_G:
        sand.fall(ax, ay, 1 + (strength > 0.7) + (strength > 1.8))
        up_x, up_y = -ax / (strength * G_PX), -ay / (strength * G_PX)
    else:
        # floating: a warmer badge makes for restless sand
        heat = 0 if sensors.temperature is None else max(0.0, sensors.temperature - 25)
        sand.stir(6 + heat * 1.5)
        up_x, up_y = 0.0, -1.0
    if badge.ticks < shake_until:
        sand.stir(70)
    sand.spawn(14, up_x, up_y)


def update_lights(dt):
    global glow, lit
    impact = scene.world.impact
    glow = max(glow * math.exp(-dt * 6), min(1.0, impact / 900))
    level = glow
    if sensors.charging:
        level = max(level, 0.08 + 0.06 * math.sin(badge.ticks / 400))
    if abs(level - lit) > 0.02 or (level == 0 and lit != 0):
        lit = level
        badge.caselights(lit)


def clock(section):
    """Per-section timings, only collected in debug mode or under a test harness."""
    if HOOK or DEBUG:
        now = time.ticks_us()
        spent = time.ticks_diff(now, timings.get("_", now))
        timings[section] = spent
        totals[section] = totals.get(section, 0) + spent
        timings["_"] = now


def report():
    frames = totals.pop("frames", 1) or 1
    parts = " ".join("%s=%.1f" % (k, v / frames / 1000) for k, v in totals.items())
    print("freefall: %.1f fps | ms: %s | mem %d | %s" % (1000 * frames / max(1, badge.ticks - totals_since[0]),
                                                      parts, gc.mem_free(), me.state))
    totals.clear()
    totals_since[0] = badge.ticks


def update():
    global frame, seen_version, grain_value, shake_until, night
    frame += 1
    dt = min(badge.ticks_delta, 100) / 1000
    now = badge.ticks
    if HOOK or DEBUG:
        timings["_"] = time.ticks_us()
        totals["frames"] = totals.get("frames", 0) + 1
        if DEBUG and frame % 150 == 0:
            report()
    if HOOK:
        HOOK(globals(), False)
    sensors.update(dt, now)
    clock("sensors")
    handle_input()
    if sensors.jolt > 30:
        shake_until = now + 250

    mult = PLANETS[planet][1]
    ax = sensors.gx * G_PX * mult + sensors.touch[0] * WIND
    ay = sensors.gy * G_PX * mult + sensors.touch[1] * WIND
    world = scene.world
    world.step(dt, ax, ay, sensors.spin * ROTATION_GAIN, sensors.spin_rate * ROTATION_GAIN)
    clock("physics")
    turn_round_bodies(dt)
    clock("turn")
    step_sand(ax, ay)
    clock("sand")
    update_lights(dt)
    clock("lights")

    me.poll(now)
    if me.version != seen_version:
        seen_version = me.version
        scene.build()
        scene.paint()
        levels, per = me.grains()
        if len(levels) != sand.count + sand.waiting:
            grain_value = pour()

    night += ((1.0 - sensors.daylight) - night) * min(1.0, dt * 2)
    clock("profile")
    draw()
    if HOOK:
        HOOK(globals(), True)


# -- drawing ---------------------------------------------------------------

def draw_sky():
    screen.pen = mix(DAY_SKY, NIGHT_SKY, night)
    screen.clear()
    if night < 0.25:
        return
    # stars drift a little as the badge tilts, for a sense of depth
    stars(screen, star_x, star_y, star_size, star_phase, STAR_COUNT, WAVE, badge.ticks // 60,
          int(256 * night), int(sensors.tilt_x * 10), int(sensors.tilt_y * 6))


def draw_plate(k, plate, lettering, length, thick, fill):
    world = scene.world
    cx, cy = world.plate_centre(plate)
    ux, uy = world.plate_axis(plate)
    angle = math.atan2(uy, ux)
    # keep the words the right way up: flip the lettering when the bar turns over
    reference = up_direction() or (0.0, -1.0)
    facing = uy * reference[0] - ux * reference[1]
    if scene.flipped[k] and facing > 0.25:
        scene.flipped[k] = False
    elif not scene.flipped[k] and facing < -0.25:
        scene.flipped[k] = True
    if scene.flipped[k]:
        angle += math.pi
    degrees = math.degrees(angle)
    bar = shape.rounded_rectangle(-length / 2, -thick / 2, length, thick, thick / 2)
    bar.transform = mat3().translate(cx, cy).rotate(degrees)
    screen.pen = fill
    screen.shape(bar)
    lettering.draw(screen, cx, cy, angle)


def draw_battery(x, y):
    level = sensors.battery if sensors.battery is not None else 0
    tone = GREEN if level > 40 else AMBER if level > 15 else RED
    screen.pen = EDGE
    screen.shape(shape.circle(x, y, BATTERY_R))
    screen.pen = COIN
    screen.shape(shape.circle(x, y, BATTERY_R - 3))
    sweep = 360 * level / 100
    screen.pen = tone
    screen.shape(shape.arc(x, y, BATTERY_R - 3, BATTERY_R, 0, sweep))
    screen.font = small
    screen.pen = WHITE
    label = "~" if sensors.charging else str(level)
    w, h = screen.measure_text(label)
    screen.text(label, x - w / 2, y - h / 2)


def draw_bodies():
    world = scene.world
    for k, art in ((0, scene.avatar_art), (1, scene.repo_art), (2, scene.contrib_art)):
        i = scene.round[k]
        art.draw(screen, world.X[i] / 256, world.Y[i] / 256, scene.angle[k])
    bx, by = world.position(scene.battery)
    draw_battery(bx, by)
    draw_plate(0, scene.name_plate, scene.name_text, scene.name_len, NAME_THICK, WHITE)
    draw_plate(1, scene.handle_plate, scene.handle_text, scene.handle_len, HANDLE_THICK, GREEN_DARK)


def draw_gauge(x, y):
    """A tiny plumb line: which way is down, and how hard."""
    screen.pen = EDGE
    screen.shape(shape.circle(x, y, 9).stroke(1.5))
    pull = sensors.pull
    if pull < ZERO_G:
        screen.pen = MUTED
        screen.shape(shape.circle(x, y, 2))
        return
    reach = min(9.0, 4 + pull * 5)
    screen.pen = GREEN
    screen.shape(shape.line(x, y, x + sensors.gx / pull * reach, y + sensors.gy / pull * reach, 2))


def draw_hud():
    name, mult = PLANETS[planet]
    pull = sensors.pull * mult
    draw_gauge(12, 12)
    screen.font = small
    screen.pen = MUTED
    state = "zero-g" if sensors.pull < ZERO_G or mult == 0 else "%.2fg" % pull
    screen.text("%s %s" % (name, state), 26, 5)
    status = me.state[:34]
    if status != "up to date":
        w, _ = screen.measure_text(status)
        screen.text(status, W - w - 6, 5)
    if banner and badge.ticks - banner_at < 1400:
        fade = 1 - (badge.ticks - banner_at) / 1400
        screen.font = heading
        screen.pen = color.rgb(240, 246, 252, int(255 * fade))
        screen.text(banner, rect(0, 26, W, 30), align=image.CENTER)
    if panel:
        draw_panel()


def draw_panel():
    s = sensors
    rows = (
        ("gravity", "%+.2f %+.2f %+.2f g" % (s.gx, s.gy, s.gz)),
        ("gyro", "%+.0f deg/s" % math.degrees(s.spin)),
        ("touch", "%+.1f %+.1f" % s.touch),
        ("light", "%d (%s)" % (s.light_raw, "day" if s.daylight > 0.5 else "night")),
        ("temp", "-" if s.temperature is None else "%.1f C" % s.temperature),
        ("battery", "-" if s.battery is None else "%d%% %.2fV%s" % (s.battery, s.voltage or 0, " usb" if s.usb else "")),
        ("wifi", "-" if s.rssi is None else "%d dBm" % s.rssi),
        ("taps", "%d single  %d double" % (s.counts.get("single_tap", 0), s.counts.get("double_tap", 0))),
        ("falls", str(s.counts.get("freefall", 0))),
        ("sand", "%d grains%s" % (sand.count, "" if grain_value == 1 else " (1 = %d)" % grain_value)),
    )
    top = 22
    screen.pen = color.rgb(13, 17, 23, 215)
    screen.rectangle(6, top, 196, 12 * len(rows) + 8)
    screen.font = small
    y = top + 4
    for label, value in rows:
        screen.pen = MUTED
        screen.text(label, 12, y)
        screen.pen = WHITE
        screen.text(value, 70, y)
        y += 12


def draw():
    draw_sky()
    clock("sky")
    sand.draw(screen)
    clock("sand_draw")
    draw_bodies()
    clock("bodies")
    draw_hud()
    clock("hud")


def on_exit():
    print("freefall: exit")
    badge.autorotate(previous_autorotate)
    badge.default_clear = previous_clear
    badge.caselights(0)


run(update)

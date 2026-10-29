"""
Every sensor on the badge, read once a frame and turned into screen terms.

Axes were measured on a real badge: held upright the accelerometer reads +1 g on
y, right edge down reads +1 g on x, flat and face up reads -1 g on z. So the pull
on screen (x right, y down) is simply (+ax, +ay). The gyro's z reads positive
while the badge turns clockwise, about 164 counts per degree per second.
"""

import math

import machine

ONE_G = 16384
GYRO_PER_RADIAN = 164 * 57.29578
SLOW_MS = 1000
EVENT_NAMES = ("single_tap", "double_tap", "freefall", "significant_motion", "tilt")


def _event_codes():
    # read the already-loaded module from sys.modules: an import statement here
    # would rebind badgeware.badge (the live badge object) to the module
    import sys
    hardware = sys.modules.get("badgeware.badge")
    if hardware is None:
        return {}
    codes = {}
    for name in EVENT_NAMES:
        code = getattr(hardware, "EVENT_" + name.upper(), None)
        if code is not None:
            codes[code] = name
    return codes


class Sensors:
    def __init__(self, badge):
        self.badge = badge
        self.read_imu = badge.imu
        # gravity on screen in g; z is into the screen
        self.gx = 0.0
        self.gy = 1.0
        self.gz = 0.0
        self.jolt = 0.0
        self.spin = 0.0
        self.spin_rate = 0.0
        self.tilt_x = 0.0
        self.tilt_y = 0.0
        self.bias = None
        self.raw = (0, ONE_G, 0, 0, 0, 0)
        self.events = []
        self.counts = {name: 0 for name in EVENT_NAMES}
        self.codes = _event_codes()
        self.touch = (0.0, 0.0)
        self.light_raw = 0
        self.light_low = None
        self.light_high = None
        self.daylight = 0.0
        self.temperature = None
        self.battery = None
        self.voltage = None
        self.charging = False
        self.usb = False
        self.rssi = None
        self.slow_at = -SLOW_MS
        try:
            self.thermometer = machine.ADC(machine.ADC.CORE_TEMP)
        except (AttributeError, ValueError, OSError):
            self.thermometer = None
        self.wlan = None

    @property
    def pull(self):
        """Size of the in-plane pull in g (0 when the badge lies flat)."""
        return math.sqrt(self.gx * self.gx + self.gy * self.gy)

    @property
    def total(self):
        return math.sqrt(self.gx * self.gx + self.gy * self.gy + self.gz * self.gz)

    def update(self, dt, now):
        reading = self.read_imu()
        self.raw = reading
        ax, ay, az, rx, ry, rz = reading
        gx, gy, gz = ax / ONE_G, ay / ONE_G, -az / ONE_G
        # sudden change in the pull, for shakes
        self.jolt = math.sqrt((gx - self.gx) ** 2 + (gy - self.gy) ** 2) / max(dt, 0.005)
        # a short smoothing keeps sensor noise out but lets shakes through
        k = min(1.0, dt / 0.02)
        self.gx += (gx - self.gx) * k
        self.gy += (gy - self.gy) * k
        self.gz += (gz - self.gz) * k

        if self.bias is None:
            self.bias = [rx, ry, rz]
        steady = abs(math.sqrt(gx * gx + gy * gy + gz * gz) - 1.0) < 0.06
        if steady and abs(rz - self.bias[2]) < 400 and abs(rx - self.bias[0]) < 400:
            # the gyro drifts with temperature; follow its resting value while still
            for axis, value in enumerate((rx, ry, rz)):
                self.bias[axis] += (value - self.bias[axis]) * 0.03
        spin = (rz - self.bias[2]) / GYRO_PER_RADIAN
        if abs(spin) < 0.06:
            spin = 0.0
        rate = (spin - self.spin) / max(dt, 0.005)
        self.spin_rate += (rate - self.spin_rate) * min(1.0, dt / 0.05)
        self.spin = spin
        # tilt toward and away from you, for parallax
        self.tilt_x += ((gx if self.pull > 0.2 else 0.0) * 0.3 - self.tilt_x) * min(1.0, dt * 3)
        self.tilt_y += (gz * 0.5 - self.tilt_y) * min(1.0, dt * 3)

        self.events = []
        try:
            for code in self.badge.imu_event():
                name = self.codes.get(code, str(code))
                self.events.append(name)
                self.counts[name] = self.counts.get(name, 0) + 1
        except (AttributeError, TypeError):
            pass

        move = self.badge.direction()
        self.touch = (move.x, move.y)

        if now - self.slow_at >= SLOW_MS:
            self.slow_at = now
            self.read_slow()

    def read_slow(self):
        badge = self.badge
        try:
            self.light_raw = badge.light_level()
        except (AttributeError, OSError):
            self.light_raw = 0
        light = self.light_raw
        if self.light_low is None:
            self.light_low = self.light_high = light
        # the range relaxes slowly so a dark room still has a day and a night
        self.light_low = min(light, self.light_low + (light - self.light_low) * 0.02)
        self.light_high = max(light, self.light_high + (light - self.light_high) * 0.02, self.light_low + 24)
        self.daylight = (light - self.light_low) / (self.light_high - self.light_low)
        try:
            self.battery = badge.battery_level()
            self.voltage = badge.battery_voltage()
            self.charging = badge.is_charging()
            self.usb = badge.usb_connected()
        except (AttributeError, OSError):
            pass
        if self.thermometer:
            volts = self.thermometer.read_u16() * 3.3 / 65535
            celsius = 27 - (volts - 0.706) / 0.001721
            self.temperature = celsius if self.temperature is None else self.temperature + (celsius - self.temperature) * 0.3
        try:
            if self.wlan is None:
                import network
                self.wlan = network.WLAN(network.STA_IF)
            self.rssi = self.wlan.status("rssi") if self.wlan.isconnected() else None
        except (OSError, ValueError, ImportError):
            self.rssi = None

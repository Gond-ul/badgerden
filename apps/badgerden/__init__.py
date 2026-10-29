"""
Badgerden: an app store for the badge, fed from public GitHub repos.

Lists the apps in each source repo's manifest.json and installs, updates or
removes them over Wi-Fi. Sources default to Gond-ul/badgerden; set
BADGERDEN_REPOS = ["you/your-repo", ...] in secrets.py to add your own.

Controls:
* Up / Down = Choose an app
* Select = Install / update
* Right = Remove (press Select to confirm)
* Left = Refresh
* Back = Return to the launcher
"""

import hints
import missing_details

import den_core

badge.mode(HIRES | VSYNC)
screen.antialias = image.X2

MISSING = missing_details.missing("WIFI_SSID")
if not MISSING:
    import wifi

WIFI_TIMEOUT = 10
WIFI_RETRIES = 100000

WIDTH = 320
STATUS_HEIGHT = 21
RIBBON_TOP = 198
TITLE_X = 8
TITLE_Y = 202
MARGIN = 4

ROW_HEIGHT = 40
ROW_GAP = 3
ROW_PITCH = ROW_HEIGHT + ROW_GAP
VISIBLE_ROWS = 4
LIST_TOP = STATUS_HEIGHT + 2

BASE_STRENGTH = 0.22
MID_STRENGTH = 0.42

PALETTE = [
    (88, 58, 247),
    (22, 143, 251),
    (15, 191, 62),
    (247, 54, 120),
]

white = color.rgb(255, 255, 255)
black = color.rgb(0, 0, 0)
dim_white = color.rgb(255, 255, 255, 140)
faint_white = color.rgb(255, 255, 255, 60)
green = color.rgb(95, 237, 131)
amber = color.rgb(255, 196, 70)
red = color.rgb(255, 98, 98)

status_font = font.salty
caption_font = font.corset
name_font = font.sins
value_font = font.ziplock
title_font = font.ignore

HINT_STYLE = hints.Style(white, dim_white, black)
HINT_SHAPE = (BUTTON_LEFT, BUTTON_RIGHT, BUTTON_SELECT)
HINT_RADIUS = 4

STATUS_TEXT = {
    den_core.NOT_INSTALLED: "get",
    den_core.INSTALLED: "installed",
    den_core.UPDATE: "update",
}
STATUS_PEN = {
    den_core.NOT_INSTALLED: white,
    den_core.INSTALLED: dim_white,
    den_core.UPDATE: amber,
}

CONNECTING = "connecting"
LOADING = "loading"
CHECKING = "checking"
BROWSING = "browsing"
CONFIRM = "confirm"
INSTALLING = "installing"
FAILED = "failed"


def shade(rgb, strength):
    return color.rgb(*(round(channel * strength) for channel in rgb))


def fit(text, width):
    if screen.measure_text(text)[0] <= width:
        return text
    while text and screen.measure_text(text + "...")[0] > width:
        text = text[:-1]
    return text + "..."


def kilobytes(size):
    return "%dKB" % max(1, (size + 1023) // 1024)


def draw_status(right_text):
    screen.font = status_font
    screen.pen = white
    screen.text("badgerden", TITLE_X, 3)
    if right_text:
        width, _ = screen.measure_text(right_text)
        screen.pen = dim_white
        screen.text(right_text, WIDTH - TITLE_X - width, 3)


def draw_ribbon(title):
    screen.font = title_font
    screen.pen = white
    screen.text(title, TITLE_X, TITLE_Y)


def draw_hint(label, lit, right):
    screen.font = caption_font
    label_width, _ = screen.measure_text(label)
    dots_width = hints.hint_width(HINT_SHAPE, HINT_RADIUS)
    left = right - label_width - 6 - dots_width
    hints.draw_hint(HINT_STYLE, HINT_SHAPE, lit, left + dots_width / 2, 219, HINT_RADIUS)
    screen.pen = dim_white
    screen.text(label, left + dots_width + 6, 213)
    return left - 12


def draw_page(heading, message, tone=dim_white, spinning=False):
    screen.font = value_font
    screen.pen = white
    width, _ = screen.measure_text(heading)
    screen.text(heading, (WIDTH - width) / 2, 70)
    screen.pen = tone
    screen.text(message, rect(20, 100, WIDTH - 40, 80), align=image.CENTER)
    if spinning:
        screen.pen = faint_white
        screen.shape(shape.arc(WIDTH / 2, 170, 10, 13, 0, 360))
        turned = badge.ticks / 1200 * 360
        screen.pen = green
        screen.shape(shape.arc(WIDTH / 2, 170, 10, 13, turned, turned + 90))


def draw_bar(left, top, width, height, done, pen):
    screen.pen = faint_white
    screen.rectangle(left, top, width, height)
    screen.pen = pen
    screen.rectangle(left, top, round(width * done), height)


class Store:
    def __init__(self):
        self.den = den_core.Den()
        self.state = CONNECTING if not MISSING else None
        self.index = 0
        self.top_row = 0
        self.checked = 0
        self.job = None
        self.message = ""
        self.notice = ""
        self.notice_pen = green
        self.shown_loading = False
        self.wifi_reason = None
        if not MISSING:
            wifi.connect(timeout=WIFI_TIMEOUT, retries=WIFI_RETRIES)

    @property
    def selected(self):
        if self.den.apps:
            return self.den.apps[self.index]
        return None

    def fail(self, error):
        print("badgerden:", repr(error))
        den_core.release()
        self.job = None
        self.state = FAILED
        self.message = str(error) or type(error).__name__

    # -- update -----------------------------------------------------------

    def update(self):
        if badge.pressed(BUTTON_BACK) and self.state != INSTALLING:
            den_core.release()
            reset()
        if MISSING:
            return

        handler = getattr(self, "update_" + self.state)
        try:
            handler()
        except Exception as error:  # noqa: BLE001
            self.fail(error)

    def update_connecting(self):
        code, saying = wifi.status()
        if code < 0:
            self.wifi_reason = saying
        if wifi.connect():
            self.wifi_reason = None
            self.state = LOADING
            return
        self.message = saying

    def update_loading(self):
        # let one frame of the loading page go up before this blocking fetch
        if not self.shown_loading:
            self.shown_loading = True
            return
        self.shown_loading = False
        self.den.refresh()
        if self.den.errors:
            self.say(self.den.errors[0], amber)
        self.checked = 0
        self.index = min(self.index, max(0, len(self.den.apps) - 1))
        self.state = CHECKING

    def update_checking(self):
        # hash one installed app per frame so the bar moves
        if self.checked < len(self.den.apps):
            self.den.apps[self.checked].check()
            self.checked += 1
            return
        self.state = BROWSING

    def update_browsing(self):
        count = len(self.den.apps)
        if count:
            if badge.pressed(BUTTON_DOWN):
                self.index = (self.index + 1) % count
            if badge.pressed(BUTTON_UP):
                self.index = (self.index - 1) % count
        self.top_row = max(min(self.top_row, self.index), self.index - VISIBLE_ROWS + 1)

        if badge.pressed(BUTTON_LEFT):
            self.refresh()
        elif badge.pressed(BUTTON_RIGHT) and self.selected and self.selected.removable:
            self.state = CONFIRM
        elif badge.pressed(BUTTON_SELECT) and self.selected and self.selected.status != den_core.INSTALLED:
            self.start(self.selected)

    def update_confirm(self):
        if badge.pressed(BUTTON_SELECT):
            app = self.selected
            self.den.remove(app)
            self.say("removed " + app.name)
            self.state = BROWSING
        elif badge.pressed(BUTTON_LEFT) or badge.pressed(BUTTON_RIGHT) or badge.pressed(BUTTON_UP) or badge.pressed(BUTTON_DOWN):
            self.state = BROWSING

    def update_installing(self):
        if self.job.step():
            app = self.job.app
            self.job = None
            self.say("installed %s %s" % (app.name, app.version))
            self.state = BROWSING

    def update_failed(self):
        if badge.pressed(BUTTON_SELECT) or badge.pressed(BUTTON_LEFT):
            self.refresh()

    def say(self, notice, pen=green):
        self.notice = notice
        self.notice_pen = pen

    def start(self, app):
        self.job = den_core.Install(app)
        self.notice = ""
        self.state = INSTALLING

    def refresh(self):
        self.message = ""
        self.notice = ""
        self.state = LOADING if wifi.is_connected() else CONNECTING

    # -- draw -------------------------------------------------------------

    def draw(self):
        screen.pen = black
        screen.clear()

        if MISSING:
            missing_details.show(MISSING, lambda: None)
            return

        right = ""
        if self.den.apps and self.state in (BROWSING, CONFIRM, INSTALLING):
            right = "%d apps" % len(self.den.apps)
        draw_status(right)
        getattr(self, "draw_" + self.state)()

    def draw_connecting(self):
        if self.wifi_reason:
            draw_page("cannot connect", self.wifi_reason + "\n\nStill trying...", amber, True)
        else:
            draw_page("connecting to wifi", self.message or "", dim_white, True)
        draw_ribbon("den")

    def draw_loading(self):
        draw_page("opening the den", ", ".join(den_core.repos()), dim_white, True)
        draw_ribbon("den")

    def draw_checking(self):
        draw_page("checking your apps", "%d of %d" % (self.checked, len(self.den.apps)))
        draw_bar(60, 140, WIDTH - 120, 4, self.checked / max(1, len(self.den.apps)), green)
        draw_ribbon("den")

    def draw_failed(self):
        draw_page("something went wrong", self.message, red)
        draw_ribbon("den")
        draw_hint("retry", (BUTTON_SELECT,), WIDTH - TITLE_X)

    def draw_list(self):
        apps = self.den.apps
        if not apps:
            draw_page("the den is empty", "No apps found in " + ", ".join(den_core.repos()))
            return
        for row in range(VISIBLE_ROWS):
            index = self.top_row + row
            if index >= len(apps):
                break
            self.draw_row(apps[index], index, LIST_TOP + row * ROW_PITCH, index == self.index)

    def draw_row(self, app, index, top, selected):
        left, width = MARGIN, WIDTH - MARGIN * 2
        rgb = PALETTE[index % len(PALETTE)]
        if selected:
            screen.pen = white
            screen.rectangle(left, top, width, ROW_HEIGHT)
            screen.pen = shade(rgb, MID_STRENGTH)
            screen.rectangle(left + 2, top + 2, width - 4, ROW_HEIGHT - 4)
        else:
            screen.pen = shade(rgb, BASE_STRENGTH)
            screen.rectangle(left, top, width, ROW_HEIGHT)

        label = STATUS_TEXT[app.status]
        screen.font = caption_font
        label_width, _ = screen.measure_text(label)
        screen.pen = STATUS_PEN[app.status]
        screen.text(label, left + width - 8 - label_width, top + 4)

        screen.font = name_font
        screen.pen = white
        screen.text(fit(app.name, width - label_width - 28), left + 8, top + 3)

        screen.font = caption_font
        screen.pen = dim_white
        detail = "%s  %s  %s" % (app.version, kilobytes(app.size), app.description)
        screen.text(fit(detail.strip(), width - 16), left + 8, top + 21)

    def draw_browsing(self):
        self.draw_list()
        app = self.selected
        if self.notice:
            screen.font = caption_font
            screen.pen = self.notice_pen
            screen.text(fit(self.notice, WIDTH - 2 * TITLE_X), TITLE_X, RIBBON_TOP - 14)
        draw_ribbon("den")
        right = WIDTH - TITLE_X
        if app and app.status == den_core.UPDATE:
            right = draw_hint("update", (BUTTON_SELECT,), right)
        elif app and app.status == den_core.NOT_INSTALLED:
            right = draw_hint("install", (BUTTON_SELECT,), right)
        if app and app.removable:
            right = draw_hint("remove", (BUTTON_RIGHT,), right)
        draw_hint("refresh", (BUTTON_LEFT,), right)

    def draw_confirm(self):
        self.draw_list()
        screen.pen = color.rgb(0, 0, 0, 200)
        screen.rectangle(0, STATUS_HEIGHT, WIDTH, RIBBON_TOP - STATUS_HEIGHT)
        draw_page("remove %s?" % self.selected.name, "Its saved progress in /state is kept.", dim_white)
        draw_ribbon("den")
        right = draw_hint("remove", (BUTTON_SELECT,), WIDTH - TITLE_X)
        draw_hint("cancel", (BUTTON_LEFT,), right)

    def draw_installing(self):
        self.draw_list()
        screen.pen = color.rgb(0, 0, 0, 200)
        screen.rectangle(0, STATUS_HEIGHT, WIDTH, RIBBON_TOP - STATUS_HEIGHT)
        job = self.job
        draw_page("installing %s" % job.app.name, job.current, dim_white)
        draw_bar(60, 150, WIDTH - 120, 4, job.progress, green)
        draw_ribbon("den")


store = Store()


def update():
    store.update()
    store.draw()


def on_exit():
    den_core.release()


run(update)

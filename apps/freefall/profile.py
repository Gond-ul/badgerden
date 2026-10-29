"""
GitHub profile data: name, handle, public repos, contributions and avatar.

Cached copies (ours, else the stock badge app's) give an instant first frame;
fresh copies download in the background with the firmware's non-blocking fetch,
so the physics never stalls on the network.
"""

import json
import os

STATE = "/state"
USER_FILE = STATE + "/freefall_user.json"
CONTRIB_FILE = STATE + "/freefall_contribs.json"
AVATAR_FILE = STATE + "/freefall_avatar.img"
STOCK_USER = STATE + "/badge_user.json"
STOCK_CONTRIB = STATE + "/badge_contribs.json"
STOCK_AVATAR = STATE + "/badge_avatar.png"

USER_URL = "https://api.github.com/users/{user}"
CONTRIB_URL = "https://github.com/{user}.contribs"
# the firmware's fetch can't parse avatars.githubusercontent.com's headers, so the
# avatar comes through the same resizing proxy the stock badge app uses, as a PNG
AVATAR_URL = "https://wsrv.nl/?url=https://github.com/{user}.png&w=144&output=png"
HEADERS = {"User-Agent": "GitHub Universe Badge 2026 freefall"}
RETRY_MS = 30000
# about a third of the screen's cells stay sand-free above this; more grains bury the scene
MAX_GRAINS = 240


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def read_json(*paths):
    for path in paths:
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return None


def grains_for(days, limit=MAX_GRAINS):
    """One grain per contribution, oldest first, coloured by that day's level.
    Above `limit` each grain stands for several contributions."""
    total = sum(count for count, _ in days)
    if not total:
        return [], 1
    per = 1
    while total / per > limit:
        per += 1
    levels = []
    carry = 0
    for count, level in days:
        carry += count
        while carry >= per:
            carry -= per
            levels.append(max(1, min(4, level)))
    return levels, per


class Profile:
    def __init__(self, handle, contact_name, wifi=None):
        self.handle = handle
        self.name = contact_name or handle or "your name"
        self.contact_name = contact_name
        self.repos = None
        self.contributions = None
        self.days = []
        self.avatar = None
        self.wifi = wifi
        self.state = "offline"
        self.queue = []
        self.download = None
        self.retry_at = 0
        # bumped whenever something the scene draws has changed
        self.version = 0
        self.load_cache()
        if handle and wifi is not None:
            self.queue = ["user", "contribs", "avatar"]
            self.state = "connecting"

    # -- cache ------------------------------------------------------------

    def load_cache(self):
        user = read_json(USER_FILE, STOCK_USER)
        if user and (user.get("login") or "").lower() == (self.handle or "").lower():
            self.apply_user(user)
        contribs = read_json(CONTRIB_FILE, STOCK_CONTRIB)
        if contribs:
            self.apply_contribs(contribs)
        for path in (AVATAR_FILE, STOCK_AVATAR):
            if exists(path):
                self.avatar = path
                break
        self.version += 1

    def apply_user(self, user):
        self.repos = user.get("public_repos")
        self.name = user.get("name") or self.contact_name or user.get("login") or self.name
        self.handle = user.get("login") or self.handle

    def apply_contribs(self, data):
        self.contributions = data.get("total_contributions")
        days = []
        for week in data.get("weeks", ()):
            for day in week.get("contribution_days", ()):
                days.append((day.get("count", 0), day.get("level", 0)))
        self.days = days

    def grains(self):
        return grains_for(self.days)

    # -- network ----------------------------------------------------------

    def poll(self, now):
        """Advance the downloads one notch. Call every frame; never blocks."""
        if not self.queue:
            return
        if self.download is None:
            if now < self.retry_at:
                return
            if not self.wifi.connect():
                code, saying = self.wifi.status()
                self.state = "wifi: " + saying if code < 0 else "connecting"
                return
            self.start(now)
            return
        request, kind, temp, final = self.download
        if request.error:
            self.fail(now, "%s: %s" % (kind, request.error))
            return
        if not request:
            self.state = "fetching " + kind
            return
        self.download = None
        try:
            self.finish(kind, temp, final)
            self.queue.pop(0)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.fail(now, "%s: %s" % (kind, error))
        if not self.queue:
            self.state = "up to date"

    def start(self, now):
        import fetch
        fetch.AsyncFetch.MAX_HEADER_BYTES = 8192
        kind = self.queue[0]
        if kind == "user":
            url, final = USER_URL.format(user=self.handle), USER_FILE
        elif kind == "contribs":
            url, final = CONTRIB_URL.format(user=self.handle), CONTRIB_FILE
        else:
            url, final = AVATAR_URL.format(user=self.handle), AVATAR_FILE
        temp = final + ".tmp"
        self.download = (fetch.url(url, headers=HEADERS).to(temp), kind, temp, final)
        self.state = "fetching " + kind

    def finish(self, kind, temp, final):
        if kind == "avatar":
            # make sure the badge can decode it before it replaces the old one
            image.load(temp, 16, 16)
        else:
            with open(temp) as f:
                data = json.load(f)
            if kind == "user":
                self.apply_user(data)
            else:
                self.apply_contribs(data)
        try:
            os.remove(final)
        except OSError:
            pass
        os.rename(temp, final)
        if kind == "avatar":
            self.avatar = final
        self.version += 1

    def fail(self, now, message):
        print("freefall:", message)
        self.download = None
        self.state = "retrying (%s)" % message
        self.retry_at = now + RETRY_MS

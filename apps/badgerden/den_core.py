"""
Badgerden core: reads app manifests from GitHub and installs apps onto the badge.

No drawing in here, so it can be driven from a REPL as well as from the app:

    import den_core
    den = den_core.Den()
    den.refresh()                  # needs Wi-Fi up
    den.install(den.apps[0])

The app disk (/system) is mounted read-only by the firmware. Installs remount it
writable for as long as they run, write into `<slug>.new`, verify every file
against its sha256, then swap it into place. A failure at any point leaves the
installed app untouched.
"""

import binascii
import gc
import hashlib
import json
import os

import requests
import rp2
import vfs

try:
    import secrets
except ImportError:
    secrets = None

DEFAULT_REPOS = ("Gond-ul/badgerden",)
BRANCH = "main"
SYSTEM = "/system"
APPS_DIR = SYSTEM + "/apps"
SELF = "badgerden"

# never touched, whatever a manifest says
PROTECTED = ("menu",)
# kept installed so the badge can always be fixed or reconfigured
UNREMOVABLE = (SELF, "menu", "mass_storage", "settings")

HEADERS = {"User-Agent": "badgerden"}
TIMEOUT = 15
CHUNK = 2048
SPARE_BYTES = 64 * 1024

NOT_INSTALLED = "get"
INSTALLED = "installed"
UPDATE = "update"

DIR = 0x4000


class DenError(Exception):
    pass


def repos():
    configured = getattr(secrets, "BADGERDEN_REPOS", None) if secrets else None
    if isinstance(configured, str):
        configured = (configured,)
    return tuple(configured or DEFAULT_REPOS)


def exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


def is_dir(path):
    try:
        return os.stat(path)[0] & DIR == DIR
    except OSError:
        return False


def rmtree(path):
    if not exists(path):
        return
    if is_dir(path):
        for entry in os.ilistdir(path):
            rmtree(path + "/" + entry[0])
        os.rmdir(path)
    else:
        os.remove(path)


def makedirs(path):
    built = ""
    for part in path.strip("/").split("/"):
        built += "/" + part
        if not exists(built):
            os.mkdir(built)


def free_bytes():
    stat = os.statvfs(SYSTEM)
    return stat[0] * stat[4]


def quote(path):
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./~"
    return "".join(c if c in safe else "%%%02X" % ord(c) for c in path)


def hexdigest(hasher):
    return binascii.hexlify(hasher.digest()).decode()


def file_sha256(path):
    hasher = hashlib.sha256()
    buffer = bytearray(CHUNK)
    view = memoryview(buffer)
    with open(path, "rb") as f:
        while True:
            n = f.readinto(buffer)
            if not n:
                break
            hasher.update(view[:n])
    return hexdigest(hasher)


def valid_slug(slug):
    if not slug or slug.startswith("."):
        return False
    return all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in slug)


def valid_path(path):
    if not path or path.startswith("/") or "\\" in path:
        return False
    return all(part and part not in (".", "..") for part in path.split("/"))


def get(url, accept=None):
    headers = dict(HEADERS)
    if accept:
        headers["Accept"] = accept
    response = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True)
    if response.status_code != 200:
        response.close()
        raise DenError("HTTP %d from %s" % (response.status_code, url.split("/")[2]))
    return response


class App:
    def __init__(self, repo, commit, data):
        self.repo = repo
        self.commit = commit
        self.slug = data["slug"]
        self.name = data.get("name") or self.slug
        self.description = data.get("description", "")
        self.version = data.get("version", "")
        self.author = data.get("author", "")
        self.files = data["files"]
        self.size = sum(f["size"] for f in self.files)
        self.status = NOT_INSTALLED

    @property
    def path(self):
        return APPS_DIR + "/" + self.slug

    def url(self, path):
        return "https://raw.githubusercontent.com/%s/%s/apps/%s/%s" % (self.repo, self.commit, self.slug, quote(path))

    def check(self):
        """Work out the status by hashing what is on the disk now."""
        if not is_dir(self.path):
            self.status = NOT_INSTALLED
            return self.status
        for entry in self.files:
            local = self.path + "/" + entry["path"]
            try:
                if os.stat(local)[6] != entry["size"] or file_sha256(local) != entry["sha256"]:
                    self.status = UPDATE
                    return self.status
            except OSError:
                self.status = UPDATE
                return self.status
        self.status = INSTALLED
        return self.status

    @property
    def removable(self):
        return self.status != NOT_INSTALLED and self.slug not in UNREMOVABLE


class Writable:
    """Remount the app disk writable for the length of a `with` block."""

    depth = 0
    cwd = "/"

    def __enter__(self):
        if Writable.depth == 0:
            # apps import their siblings through cwd, so it is put back after
            Writable.cwd = os.getcwd()
            os.chdir("/")
            vfs.umount(SYSTEM)
            try:
                vfs.mount(vfs.VfsFat(rp2.Flash()), SYSTEM)
            except Exception:
                vfs.mount(vfs.VfsFat(rp2.Flash()), SYSTEM, readonly=True)
                raise
            recover()
        Writable.depth += 1
        return self

    def __exit__(self, *_):
        Writable.depth -= 1
        if Writable.depth == 0:
            os.chdir("/")
            vfs.umount(SYSTEM)
            vfs.mount(vfs.VfsFat(rp2.Flash()), SYSTEM, readonly=True)
            try:
                os.chdir(Writable.cwd)
            except OSError:
                pass


def release():
    """Drop back to read-only whatever state an interrupted job left behind."""
    if Writable.depth:
        Writable.depth = 1
        Writable().__exit__()


def recover():
    """Tidy up after a power cut part way through a swap."""
    for entry in os.ilistdir(APPS_DIR):
        name = entry[0]
        if name.endswith(".old"):
            slug = name[:-4]
            if exists(APPS_DIR + "/" + slug):
                rmtree(APPS_DIR + "/" + name)
            else:
                os.rename(APPS_DIR + "/" + name, APPS_DIR + "/" + slug)
        elif name.endswith(".new"):
            rmtree(APPS_DIR + "/" + name)


class Install:
    """One app install, advanced a file at a time so a UI can draw between steps."""

    def __init__(self, app):
        if app.slug in PROTECTED:
            raise DenError("%s is protected" % app.slug)
        needed = app.size + SPARE_BYTES
        if free_bytes() < needed:
            raise DenError("needs %dKB, %dKB free" % (needed // 1024, free_bytes() // 1024))
        self.app = app
        self.index = 0
        self.staging = app.path + ".new"
        self.done = False
        self.writable = Writable().__enter__()
        try:
            rmtree(self.staging)
            os.mkdir(self.staging)
        except Exception:
            self.abort()
            raise

    @property
    def progress(self):
        return self.index / max(1, len(self.app.files))

    @property
    def current(self):
        if self.index < len(self.app.files):
            return self.app.files[self.index]["path"]
        return ""

    def step(self):
        """Fetch the next file, or finish. Returns True once the app is in place."""
        try:
            if self.index < len(self.app.files):
                self.fetch(self.app.files[self.index])
                self.index += 1
                # each HTTPS request leaves a TLS context behind
                gc.collect()
                return False
            self.swap()
            return True
        except Exception:
            self.abort()
            raise

    def fetch(self, entry):
        path = entry["path"]
        if not valid_path(path):
            raise DenError("bad path %s" % path)
        target = self.staging + "/" + path
        if "/" in path:
            makedirs(target.rsplit("/", 1)[0])
        response = get(self.app.url(path))
        hasher = hashlib.sha256()
        size = 0
        try:
            with open(target, "wb") as f:
                while True:
                    chunk = response.raw.read(CHUNK)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    f.write(chunk)
                    size += len(chunk)
        finally:
            response.close()
        if size != entry["size"] or hexdigest(hasher) != entry["sha256"]:
            raise DenError("%s failed its checksum" % path)

    def swap(self):
        live = self.app.path
        old = live + ".old"
        rmtree(old)
        if exists(live):
            os.rename(live, old)
        os.rename(self.staging, live)
        rmtree(old)
        self.finish()
        self.app.status = INSTALLED

    def abort(self):
        try:
            rmtree(self.staging)
        except OSError:
            pass
        self.finish()

    def finish(self):
        if not self.done:
            self.done = True
            self.writable.__exit__()


class Den:
    def __init__(self):
        self.apps = []
        self.errors = []

    def refresh(self):
        """Load every source's manifest at its latest commit. Needs Wi-Fi."""
        apps = []
        seen = set()
        self.errors = []
        for repo in repos():
            try:
                for app in self.load(repo):
                    if app.slug not in seen:
                        seen.add(app.slug)
                        apps.append(app)
            except Exception as error:  # noqa: BLE001
                self.errors.append("%s: %s" % (repo, error))
        self.apps = apps
        if not apps and self.errors:
            raise DenError(self.errors[0])
        return apps

    def load(self, repo):
        commit = self.latest(repo)
        response = get("https://raw.githubusercontent.com/%s/%s/manifest.json" % (repo, commit))
        try:
            manifest = json.loads(response.content)
        finally:
            response.close()
        apps = []
        for data in manifest.get("apps", ()):
            if not valid_slug(data.get("slug")) or data["slug"] in PROTECTED:
                continue
            if not all(valid_path(f.get("path", "")) for f in data.get("files", ())):
                continue
            apps.append(App(repo, commit, data))
        return apps

    def latest(self, repo):
        # pin everything to one commit so the manifest and files can't disagree
        response = get("https://api.github.com/repos/%s/commits/%s" % (repo, BRANCH), "application/vnd.github.sha")
        try:
            commit = response.content.decode().strip()
        finally:
            response.close()
        if len(commit) != 40:
            raise DenError("could not read latest commit")
        return commit

    def install(self, app):
        job = Install(app)
        while not job.step():
            pass
        return app

    def remove(self, app):
        if not app.removable:
            raise DenError("%s can't be removed" % app.name)
        with Writable():
            os.rename(app.path, app.path + ".old")
            rmtree(app.path + ".old")
        app.status = NOT_INSTALLED

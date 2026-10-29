# badgerden 🦡

An app store for the GitHub Universe 2026 badge (Badger 2350, MonaOS 4).
Push an app to this repo, open **Badgerden** on the badge, press Select. No cable.

## How it works

```
you: git push ──► GitHub Action rebuilds manifest.json
                          │
badge: Badgerden ──Wi-Fi──► api.github.com    latest commit on main
                          ► raw.githubusercontent.com/<commit>/manifest.json
                          ► raw.githubusercontent.com/<commit>/apps/<slug>/...
```

- Everything is pinned to one commit, so the manifest and the files can't disagree.
- Every file is checked against its sha256 before anything is replaced.
- Installs go into `/system/apps/<slug>.new` and are swapped in only once complete.
  A failed download or a dropped connection leaves the installed app alone, and
  leftovers from a power cut are tidied up the next time Badgerden writes.
- The app disk is read-only while the badge runs. Badgerden remounts it writable
  only while it installs or removes, then puts it back.

## On the badge

| Button | Does |
| --- | --- |
| Up / Down | Choose an app |
| Select | Install or update |
| Right | Remove (Select to confirm) |
| Left | Refresh |
| Back | Back to the launcher, which picks up the changes |

Each app shows **get**, **installed** or **update**. Status comes from hashing
what's actually on the disk, so an app you copied over USB shows as installed if
it matches.

Safety rails:
- `menu` is never touched, whatever a manifest says.
- Badgerden, Settings, Mass Storage and the menu can't be removed.
- Saved progress lives in `/state`, which Badgerden never touches, so removing
  and reinstalling an app keeps your saves.
- Badgerden never reads or writes `secrets.py`.

If an app ever breaks the badge, double-tap reset to get into USB disk mode;
that's built into the firmware and doesn't depend on anything on the disk.

## Adding an app

1. Copy `apps/hello_den` to `apps/<your_slug>` (lowercase, digits, `_`).
   The folder name is what it installs as on the badge.
2. Edit `app.json`:
   ```json
   {
     "name": "My App",
     "description": "One line for the store listing",
     "version": "1.0.0",
     "author": "you",
     "exclude": ["notes/*"]
   }
   ```
3. `git push`. The Action rebuilds `manifest.json` in about 30 seconds.
   You can also run `python3 tools/build_manifest.py` yourself and commit it.

Files that never go to the badge: `app.json`, `*.md`, `*.svg`, `screenshot*`,
dotfiles and `__pycache__`, plus anything in `exclude`.

## More sources

Badgerden reads `Gond-ul/badgerden` by default. To add friends' repos (same
layout: `manifest.json` plus `apps/`), add this to `secrets.py` on the badge:

```python
BADGERDEN_REPOS = ["Gond-ul/badgerden", "friend/their-badge-apps"]
```

If two repos have the same slug, the first one listed wins. Only add repos you
trust: an app can do anything on the badge.

## First install

Badgerden can't install itself the first time. Put the badge in disk mode and
copy `apps/badgerden/` (just the `.py` files) to `BADGER/apps/badgerden/`.
After that it updates itself like any other app.

## Limits

- Public repos only (no token on the badge).
- Unauthenticated GitHub API: 60 refreshes an hour per network.
- The built-in MonaOS apps aren't published here, since their licence isn't public.

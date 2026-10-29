# Freefall

Your GitHub profile in a box that knows which way is down.

Your avatar, name, handle, public repo count and contributions are physical
objects that fall, roll and tumble with the real gravity the badge feels. Your
last year of contributions pours in as sand, one grain per few contributions,
coloured like your contribution graph.

## Every sensor does something

| Sensor | In the box |
| --- | --- |
| Accelerometer | Which way is down. Tilt to pour, shake to slosh, lay the badge flat for zero-g |
| Gyroscope | Spin the badge and things swirl, fling outward and counter-rotate |
| Tap detector | Tap the case to knock things over; double tap to launch them |
| Free-fall detector | Drop it (onto something soft) and it notices |
| Touch d-pad | Blows wind in the direction you touch |
| Light sensor | Day and night sky; cover the sensor and the stars come out |
| Temperature | A warmer badge makes floating sand more restless |
| Battery | The little ring ball is your battery level; it pulses the case lights while charging |
| Wi-Fi | Signal strength in the sensor panel, and it fetches your stats |
| Case lights | Flash when things hit the walls |

## Controls

- **Select**: jump
- **Up / Down buttons**: change planet (Earth, Moon, Mars, Jupiter, deep space)
- **Menu**: sensor panel with live readings
- **Back**: return to the launcher

## Data

Uses `GITHUB_USERNAME` (and `CONTACT_NAME` as a fallback name) from `secrets.py`
and Wi-Fi to fetch:

- name and **public** repo count from `api.github.com/users/<you>` (private repos
  would need a token on the badge, which isn't worth the risk on a device that
  mounts as a USB drive)
- contributions from `github.com/<you>.contribs`, the same source as the stock
  badge app, which includes private contributions
- your avatar, through the same `wsrv.nl` resizer the stock badge app uses

Everything is cached in `/state`, so it works offline after the first fetch, and
it starts from the stock badge app's cache if that's all there is.

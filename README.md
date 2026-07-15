# CinaCue

A small, self-hosted **movie channel** for Unraid. Point it at your existing
Plex library, build a **daily lineup**, and CinaCue broadcasts it like a live TV
station: one GPU-encoded stream that everyone tunes into at the same live
position — not a per-user, on-demand player.

- **Daily, repeating schedule.** Movies sit at a time of day and air every
  on-air day. Turn individual weekdays off and the channel goes off air those
  days. A late movie that starts on an on-air day plays through past midnight.
- **Live, in-browser viewer.** Open the page and the current movie is playing,
  joined at its live position. Between movies (or on off days) it shows a tidy
  "off air" card with what's next.
- **One encode for everyone.** A single NVENC stream is shared by all viewers,
  so the GPU cost is fixed no matter how many people watch — bandwidth is the
  only thing that scales with your audience.

It ships as a prebuilt image on GHCR and is built + published by CI on every
push to `main`.

---

## How it works

- **Broadcast model.** A background controller reconciles the schedule every few
  seconds and drives exactly one FFmpeg process (CUDA decode → `h264_nvenc`
  encode → HLS). It joins the active movie at the correct wall-clock offset,
  transitions between movies, goes off air during gaps and off days, and
  **self-heals** — it backs off and keeps retrying instead of giving up, and
  clears its crash budget after a clean run.
- **Pre-roll.** FFmpeg warms up a configurable number of seconds *before* a
  movie's start (`CHANNEL_PREROLL_SECONDS`, default 30) so segments exist by air
  time and viewers get instant playback instead of a cold-start spinner.
- **HLS everywhere.** The stream is served at `/stream/channel.m3u8`. Watch it in
  the built-in browser player, or point VLC / a smart-TV / an IPTV client at that
  URL — it behaves like any live channel.
- **No upscaling, ever.** The configured resolution is a *ceiling*, never a
  target (see below).

---

## The app

**Viewer** (`/`) — player-first: the movie fills the frame with an auto-hiding
overlay (title, live scrubber, mute/fullscreen), a single top-bar status
(On Air / Off Air), and an "Up Next" rail. Optionally gated by a shared code
(below). Autoplay starts muted per browser policy, with a one-time "Tap For
Sound" prompt.

**Admin** (`/admin`):

- **Dashboard** — Start/Stop, live tiles (now playing, live position, output,
  source, FFmpeg, **GPU encode % + card name**, **uptime**, up next), one-tap
  system checks (Plex, mount, RAM buffer, NVENC), and a rolling activity log.
- **Schedule** — the daily lineup as a timeline plus a row of **on-air day
  bulbs**. Add a movie by searching Plex, pick a time; overlaps are rejected.
- **Encoding** — max resolution, bitrate, audio, preset, with a live output
  preview (per-viewer bandwidth, rewind buffer).

---

## Deploy on Unraid (prebuilt image)

The image is published at **`ghcr.io/mmagtech/cinacue:latest`**. Easiest path is
the **Compose Manager** plugin.

1. Install **Compose Manager** (and the **Nvidia Driver** plugin) from Community
   Applications.
2. New stack → paste [`docker-compose.unraid.yml`](docker-compose.unraid.yml).
   It pulls the GHCR image (no local build), runs with `runtime: nvidia`, serves
   host port **8090**, and puts HLS output on a tmpfs RAM disk.
3. Create a `.env` next to it with at least `ADMIN_PASSWORD` and your Plex
   details, then **Compose Up**.

```bash
docker pull ghcr.io/mmagtech/cinacue:latest   # to update later, then Down/Up
```

**Volumes** (adjust host paths to your shares):

| Container path  | Host mapping                          | Purpose                           |
| --------------- | ------------------------------------- | --------------------------------- |
| `/config`       | `/mnt/user/appdata/cinacue`           | SQLite DB, app secret, admin hash |
| `/data/movies`  | your movie share *(read-only)*        | The movie library                 |
| `/stream`       | tmpfs (RAM)                           | HLS segments                      |

**Path translation matters.** CinaCue reads the file at the path Plex reports.
Mount the library so the container sees it at the same path, and set
`PLEX_PATH_PREFIX` / `LOCAL_PATH_PREFIX` to match — e.g. if Plex reports
`/data/movies/...`, mount your share at `/data/movies` and set both prefixes to
`/data/movies`. The admin's "file found" check catches mismatches before you
schedule a title.

**NVIDIA.** Needs the Nvidia Driver plugin; the compose sets `runtime: nvidia`,
`NVIDIA_VISIBLE_DEVICES`, and the modern `deploy.resources` reservation.

**Reverse proxy.** The compose includes optional **Traefik** labels (hostname
routing + HTTPS). Behind HTTPS, set `SESSION_COOKIE_SECURE=true`. The app runs
uvicorn with `--proxy-headers` so per-IP rate limits and logs see the real
client through the proxy.

---

## Access & security

- **Admin** — bcrypt password (seeded once from `ADMIN_PASSWORD`, then stored as
  a hash in `/config`), signed HTTP-only `SameSite=Lax` session cookie, CSRF on
  every write, and login rate limiting. No default password.
- **Optional shared viewer code** — set `PUBLIC_ACCESS_CODE` and the viewer page,
  public API, **and** the raw HLS stream all require it. Friends enter it once
  (7-day cookie); wrong entries lock out an IP for 15 minutes. Leave it blank and
  the viewer stays open (LAN use).
- Baseline security headers, a non-root container (drops privileges via `gosu`
  after fixing bind-mount ownership), and public responses that never leak the
  Plex token, server URL, or filesystem paths.

---

## Environment variables

| Variable                  | Default            | Notes                                                        |
| ------------------------- | ------------------ | ------------------------------------------------------------ |
| `TZ`                      | `America/New_York` | Channel timezone. Slots are wall-clock local; stored in UTC. |
| `ADMIN_PASSWORD`          | *(empty)*          | Seeds admin on first run. No default. Remove after.          |
| `PUBLIC_ACCESS_CODE`      | *(empty)*          | Shared viewer code. Blank = open viewer.                     |
| `SESSION_COOKIE_SECURE`   | `false`            | Set `true` behind HTTPS.                                     |
| `PLEX_URL`                | —                  | e.g. `http://host:32400`.                                    |
| `PLEX_TOKEN`              | *(empty)*          | Server-side only; never sent to the browser.                |
| `PLEX_LIBRARY_NAME`       | `Movies`           | Plex movie library name.                                     |
| `PLEX_PATH_PREFIX`        | `/movies`          | How Plex reports paths.                                      |
| `LOCAL_PATH_PREFIX`       | `/media/movies`    | Where the library is mounted in the container.              |
| `MAX_RESOLUTION`          | `1080p`            | `original` \| `1080p` \| `720p` \| `480p`. A ceiling.        |
| `VIDEO_BITRATE_KBPS`      | `8000`             | Channel-wide target bitrate.                                 |
| `AUDIO_BITRATE_KBPS`      | `192`              | 128 / 160 / 192 / 256.                                       |
| `ENCODER`                 | `h264_nvenc`       | GPU encoder.                                                 |
| `ENCODER_PRESET`          | `balanced`         | `fast` \| `balanced` \| `quality`.                           |
| `CHANNEL_AUTO_START`      | `false`            | Arm the channel on startup (idle in gaps, wake for movies).  |
| `CHANNEL_PREROLL_SECONDS` | `30`               | Warm FFmpeg up this long before a movie. `0` disables.       |
| `NVIDIA_VISIBLE_DEVICES`  | `all`              | Pin to a GPU UUID (`nvidia-smi -L`) to restrict.             |
| `CONFIG_DIR`              | `/config`          | Persistent appdata.                                          |
| `STREAM_DIR`              | `/stream`          | RAM-backed HLS output.                                       |
| `LOG_LEVEL`               | `INFO`             | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`.                    |

On-air days are set in the admin UI (stored as a bitmask in settings), not via
env.

---

## The no-upscaling rule

The configured resolution is a **maximum**, never a target. Aspect ratio is
always preserved; output is never cropped or stretched; final dimensions are
always even (H.264/yuv420p). `app/encoding.py::calculate_output_dimensions`
enforces it and is covered by `tests/test_no_upscaling.py`:

```text
3840x2160, max 1080p  -> 1920x1080
1920x1080, max 1080p  -> 1920x1080
1280x720,  max 1080p  -> 1280x720   (no enlargement)
1920x800,  max 720p   -> 1280x532   (aspect preserved, no crop)
```

---

## Develop locally

Python 3.10+ and Node 18+.

```bash
# Backend
pip install -r requirements.txt
export ADMIN_PASSWORD="choose-a-strong-password"
export CONFIG_DIR=./data/config STREAM_DIR=./data/stream
uvicorn app.main:app --reload --port 8000

# Frontend (build into app/static, which the backend serves)
cd frontend && npm install && npm run build

# Tests
python -m pytest -q
```

Then open <http://localhost:8000/> (viewer) and <http://localhost:8000/admin>.
Use `docker-compose.local.yml` for a GPU-less desktop run (software encoder).
The test suite is **110+ tests**, including schedule recurrence, the access-code
gate/lockout, no-upscaling, and a real software-FFmpeg HLS encode.

---

## Project layout

```text
CinaCue/
├── app/                     FastAPI backend
│   ├── main.py              entrypoint, health, SPA, stream-access + header middleware
│   ├── config.py            env-based settings
│   ├── database.py          SQLite engine, seeding, in-place migrations
│   ├── models.py            settings (+ active_days_mask) + scheduled_movies (daily slot)
│   ├── auth.py              admin password/session/CSRF + public access code + lockout
│   ├── scheduler.py         daily recurrence, active-days, overlap, offset, tz helpers
│   ├── stream_manager.py    FFmpeg process control + HLS + states
│   ├── stream_scheduler.py  background loop: schedule -> FFmpeg, self-healing, pre-roll
│   ├── encoding.py          no-upscale calc + FFmpeg arg builder (real-time, keyframe-aligned)
│   ├── gpu.py               nvidia-smi poll (name + encoder %) for the dashboard
│   ├── plex_client.py       Plex API client + path translation
│   ├── public_api.py        /api/public/* (read-only + access gate)
│   ├── admin_api.py         /api/admin/* (auth + CSRF)
│   └── static/              compiled frontend (npm run build)
├── frontend/src/pages/      Public, AdminApp, AdminLogin, Dashboard, Schedule, Encoding
├── assets/                  Unraid container icons (default: icon-mono-white.png)
├── docker-compose.unraid.yml   prebuilt GHCR image + Traefik (production)
├── docker-compose.local.yml    desktop/dev (software encoder)
├── Dockerfile               CUDA + FFmpeg/NVENC, Node build stage, gosu, healthcheck
├── .github/workflows/docker.yml  CI: build + publish to GHCR on push to main
└── tests/                   pytest suite
```

---

## Verify NVENC on your host

```bash
docker exec cinacue ffmpeg -hide_banner -f lavfi -i testsrc=size=1280x720:rate=30 \
  -t 2 -c:v h264_nvenc -f null -
```

A clean run (no CUDA/NVENC errors) confirms hardware encoding. The dashboard's
system checks report the same, and the app never silently falls back to CPU.

"""Design tokens, tunables, and palettes.

One palette. One source of truth. Every widget reads from here.
"""

from __future__ import annotations

from dataclasses import dataclass

APP_NAME = "Hearth"
APP_TAGLINE = "keep the fire warm"
PLAYLIST_SUFFIX = ".hearthplaylist.json"
ORG_NAME = "hearth"
APP_AUTHOR = "Mayank Bhaskar (qtjg)"
REPO_URL = "https://github.com/qtjg/hearth"

# --- geometry ---
RIBBON_WIDTH = 380
RIBBON_HEIGHT = 68
PANEL_WIDTH = 430
PANEL_HEIGHT = 610
TOAST_WIDTH = 300
TOAST_HEIGHT = 68
TOAST_LIFETIME_MS = 3500

# --- main window (the big stage) ---
WINDOW_WIDTH = 1200
WINDOW_HEIGHT = 780
SIDEBAR_WIDTH = 232
PLAYERBAR_HEIGHT = 88
QUEUE_WIDTH = 300
COVER_TILE = 168
ROW_HEIGHT = 52

# Home shelves are seeded from these guest-API searches (fast, no login).
QUICK_PICKS = (
    "today's top hits",
    "chill lofi beats",
    "classic rock anthems",
    "focus flow",
    "late night drive",
    "acoustic mornings",
)

# --- radio / autoplay ---
RADIO_LIMIT = 25          # tracks fetched per Start Radio / autoplay refill
AUTOPLAY_DEFAULT = True   # keep the music alive when the queue runs dry

# --- now playing view ---
NOW_COVER = 240

# --- timing tunables ---
SEARCH_DEBOUNCE_MS = 350
SEEK_POLL_MS = 500
FADE_STEPS = 15
FADE_INTERVAL_MS = 1000  # total sleep-timer fade window (steps * interval)

# Stream self-healing: YouTube's single-shot URLs occasionally die mid-song
# (CDN 403, connection drop) and QMediaPlayer just sits down without us.
STREAM_MAX_RECOVERIES = 3         # rejoin attempts per track before giving up
STREAM_RECOVERY_RESET_MS = 30_000  # this much healthy playback renews the budget
STREAM_RESUME_BACKSTEP_MS = 1_200  # rewind a little on rejoin so we never land on the last byte
STALL_POLLS = 24                   # frozen position while "playing" for this many polls = dead stream
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5

# --- audio tunables ---
VOLUME_TARGET_DB = -16.0
MAX_GAIN_DB = 6.0
MIN_GAIN_DB = -6.0
PLAYBACK_RATES = (0.75, 1.0, 1.25, 1.5)

# --- v0.5.0: search scopes, top tracks, shortcuts ---
SEEK_STEP_MS = 10_000        # ←/→ keyboard seek step
VOLUME_STEP = 0.05           # ↑/↓ keyboard volume step
TOP_TRACKS_LIMIT = 8         # home shelf ranking size

# --- v0.7.0: memory & rituals ---
ON_REPEAT_SHELF_LIMIT = 12        # home shelf size for the On Repeat row
ON_REPEAT_HALF_LIFE_DAYS = 7.0    # decay: last week beats last year
SESSION_MAX_HISTORY = 50          # snapshot keeps the newest 50 played
SESSION_MAX_UPCOMING = 200        # snapshot keeps at most this many upcoming

# --- v0.6.0: discover (the whole world's music) ---
DISCOVER_PLAYLIST_LIMIT = 300   # max tracks pulled per curated playlist page
DISCOVER_CARD_SIZE = 150        # square thumbnail size of discover shelf cards
WORLD_STATION_LIMIT = 20        # tracks fetched per world-genre station tune-in

# --- v0.6.1: artist spotlight + synced lyrics ---
LRCLIB_URL = "https://lrclib.net/api"   # free, keyless lyrics database
LRCLIB_TIMEOUT = 10                      # seconds per lyrics request
ARTIST_AVATAR = 132                      # artist page avatar size
ARTIST_CARD_SIZE = 132                   # release card size on the artist page

# --- v0.7.0: memory & rituals ---
ON_REPEAT_LIMIT = 25           # auto top-N computed from decayed play counts
ON_REPEAT_DECAY_DAYS = 14.0    # recency weight: last week beats last year
HISTORY_PAGE_SIZE = 100        # rows per day-jump page in the history view
QUEUE_SAVE_DEBOUNCE_MS = 1500  # coalesce queue-persistence writes
STATS_TOP_LIMIT = 10           # rows per top-artist / top-track stat card
GLOW_MIX_SIZE = 30             # tracks pulled into a one-tap Glow Mix

# --- opt-in bridges & services (guarded imports, silent when absent) ---
DISCORD_RPC_ENABLED = False    # Discord Rich Presence via pypresence (opt-in)
MPRIS_ENABLED = True           # MPRIS2 dbus service (Linux only, guarded)
UPDATE_CHECK_ENABLED = False   # "a newer hearth is lit" whisper (opt-in)
UPDATE_CHECK_INTERVAL_H = 12   # hours between release checks

# --- v0.8.0: the wider stage ---
LYRICS_OVERLAY_ENABLED = False  # frameless always-on-top lyric strip (opt-in)
THEATER_ENABLED = True          # full-screen Now Playing mode
VISUALIZER_BARS = 24            # mini-visualizer bar count in the player bar
ALARM_DEFAULT_MINUTES = 30      # wake-up alarm default lead time
THEATER_COVER = 380             # giant cover side inside theater mode

# --- v0.8.0: lyrics settings (font presets for Now Playing + the overlay) ---
LYRICS_SIZE_PRESETS = {"S": 20, "M": 28, "L": 40}   # px per S/M/L key
LYRICS_DEFAULT_SIZE_KEY = "M"                        # fallback when unset/unknown
LYRICS_FONT_FAMILIES = ("Segoe UI", "Inter", "Georgia", "Consolas")

# --- v0.8.0: the style closet (glass looks + custom wallpaper engine) ---
STYLE_DEFAULT = "hearth"          # the classic warm-gradient look
WALLPAPER_ALPHA_DEFAULT = 80      # how much UI skin lets a wallpaper glow through
WALLPAPER_ALPHA_MIN = 30
WALLPAPER_ALPHA_MAX = 100
WALLPAPER_MAX_DIM = 2560          # imported wallpapers are downscaled to this edge
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")

# --- v1.0.0 groundwork ---
CROSSFADE_ENABLED = False       # opt-in dual-player crossfade
CROSSFADE_MAX_MS = 3000         # upper bound of the crossfade slider
CROSSFADE_TICK_MS = 100         # ramp resolution: ten volume steps per second
CROSSFADE_DEFAULT_SECONDS = 0   # off until the user drags the slider

# --- v0.8.0 controls: smart shuffle, wake-up alarm, mini-visualizer ---
SMART_SHUFFLE = False            # artist-spread shuffle instead of pure random (opt-in)
SMART_SHUFFLE_RECENT_IDS = 48    # smart shuffle never replays the last N played ids
ALARM_FADE_MS = 20_000           # wake-up fade-in window (silence → pre-alarm volume)
ALARM_FADE_STEPS = 10            # steps inside that window
VISUALIZER_TICK_MS = 60          # mini-visualizer animation frame

# --- v0.7.1: ember tending (completers for the Big Burn rows) ---
SMART_SHUFFLE_WEIGHT_GAIN = 0.35    # hot tracks' wait stretches up to 35%
SMART_SHUFFLE_WEIGHTS_LIMIT = 200   # On Repeat scores pulled into a shuffle
WRAPPED_TOP_LIMIT = 5               # rows per top-artist / top-track Wrapped card

# --- v0.7.0: plugins + the local library (your own files by the fire) ---
PLUGINS_DIR_NAME = "plugins"     # folder under the app data dir holding plugins
PLUGIN_BOOT_TIMEOUT_S = 10.0     # boot plugin load is time-boxed, never delays
LOCAL_AUDIO_SUFFIXES = (".mp3", ".flac", ".ogg", ".m4a", ".wav")
LOCAL_SCAN_CAP = 5000            # max audio files per scan
LOCAL_SCAN_TIMEOUT_S = 60.0      # soft wall-clock budget for a scan walk

# --- v0.7.0: ambient mixer + i18n + last.fm groundwork (31-c5c) ---
AMBIENT_DEFAULT_LEVEL = 0.35  # campfire/rain bed loudness (0..1)
AMBIENT_LEVELS = (0.25, 0.35, 0.5, 0.7)  # tray level submenu choices
AMBIENT_TICK_MS = 100         # ambient pull cadence (~2205 frames per tick)
I18N_LANG = "en"              # tray label scaffold: "en", partial "hi"/"es"
LASTFM_API_KEY = ""           # user keys; empty = the scrobble bridge sleeps
LASTFM_SECRET = ""
LASTFM_ENABLED = False        # opt-in; not wired into playback (roadmap guardrail)

# --- v0.7.0 finale (31-c6): Discord Rich Presence + the Glow Mix ---
DISCORD_CLIENT_ID = ""          # user-set Discord application id; empty = presence sleeps
DISCORD_RPC_THROTTLE_S = 15.0   # at most one presence push per 15 s (track changes always push)
DISCORD_RPC_BACKOFF_S = 60.0    # after a failed connect/update, wait this long before retrying
GLOW_MIX_ARTISTS = 3            # top rotation artists whose kindred tracks feed the Glow Mix
GLOW_MIX_ROTATION_SHARE = 0.6   # ~60% of the blend comes from your rotation
HISTORY_CHIP_DAYS = 14          # day-jump chips shown on the history page

VERSION = "0.7.2"

REPEAT_OFF = "off"
REPEAT_ALL = "all"
REPEAT_ONE = "one"
REPEAT_MODES = (REPEAT_OFF, REPEAT_ALL, REPEAT_ONE)

# --- logging ---
LOG_MAX_BYTES = 2_000_000
LOG_BACKUPS = 3

# --- default hotkeys (app-scope QShortcut chords) ---
DEFAULT_HOTKEYS = {
    "play_pause": "Ctrl+Alt+Space",
    "next_track": "Ctrl+Alt+Right",
    "prev_track": "Ctrl+Alt+Left",
    "toggle_panel": "Ctrl+Alt+E",
    "focus_search": "Ctrl+Alt+F",
}

# System chords that should never be bound in the app.
RESERVED_CHORDS = (
    "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ctrl+Z", "Ctrl+A", "Ctrl+S",
    "Ctrl+W", "Ctrl+Q", "Ctrl+T", "Ctrl+N",
    "Alt+F4", "Alt+Tab", "Alt+Space",
    "Meta+L", "Meta+D", "Meta+E", "Meta+R",
)


@dataclass(frozen=True)
class Palette:
    """A hand-tuned color scheme. All values are #rrggbb."""

    key: str
    label: str
    bg: str
    surface: str
    surface_alt: str
    hairline: str
    text: str
    text_dim: str
    accent: str
    accent_soft: str
    danger: str
    success: str
    selection: str
    scroll: str


PALETTES: dict[str, Palette] = {
    "hearthlight": Palette(
        key="hearthlight", label="Hearthlight",
        bg="#14100c", surface="#1d1712", surface_alt="#282017",
        hairline="#3a2f22", text="#f3e9d8", text_dim="#a89880",
        accent="#f0a437", accent_soft="#f6c97e", danger="#e2694f",
        success="#8fbf6f", selection="#4a3517", scroll="#3a2f22",
    ),
    "emberfall": Palette(
        key="emberfall", label="Emberfall",
        bg="#160d0d", surface="#211313", surface_alt="#2e1a1a",
        hairline="#412525", text="#f5e6e0", text_dim="#ab8d86",
        accent="#ef6f4f", accent_soft="#f79d82", danger="#e04a3a",
        success="#9fbf6f", selection="#4a2018", scroll="#412525",
    ),
    "frost": Palette(
        key="frost", label="Frost",
        bg="#0c1216", surface="#121b21", surface_alt="#1a262e",
        hairline="#24343f", text="#e8f1f5", text_dim="#8ba3b0",
        accent="#5fc8e8", accent_soft="#9adcf0", danger="#e2694f",
        success="#7fd0a0", selection="#173a4a", scroll="#24343f",
    ),
    "moss": Palette(
        key="moss", label="Moss",
        bg="#0f130d", surface="#161c12", surface_alt="#1f2819",
        hairline="#2c3a22", text="#eef2e4", text_dim="#9aa889",
        accent="#a3c96a", accent_soft="#c7e09a", danger="#e2694f",
        success="#8fd07a", selection="#2c3d17", scroll="#2c3a22",
    ),
    "orchid": Palette(
        key="orchid", label="Orchid",
        bg="#120f16", surface="#1a1522", surface_alt="#241c30",
        hairline="#342847", text="#f2ecf7", text_dim="#a394b5",
        accent="#c08df0", accent_soft="#dcbcf7", danger="#e2694f",
        success="#8fbf9f", selection="#3a2550", scroll="#342847",
    ),
    "slate": Palette(
        key="slate", label="Slate",
        bg="#101314", surface="#181d1f", surface_alt="#212829",
        hairline="#2e383a", text="#ecf0f0", text_dim="#96a3a3",
        accent="#5fd4c4", accent_soft="#9ae8dc", danger="#e2694f",
        success="#7fd0a0", selection="#1d3c38", scroll="#2e383a",
    ),
    "grove": Palette(
        key="grove", label="Grove",
        bg="#0e1210", surface="#131917", surface_alt="#1a2420",
        hairline="#223029", text="#e8f5ee", text_dim="#93a89d",
        accent="#1db954", accent_soft="#52e08a", danger="#e2694f",
        success="#7fd0a0", selection="#14422a", scroll="#223029",
    ),
}

DEFAULT_PALETTE = "grove"

# Keys shipped with the app — imported packs may never overwrite these.
BUILTIN_PALETTE_KEYS = frozenset(PALETTES)


def get_palette(key: str | None) -> Palette:
    """Look up a palette by key, falling back to the default."""
    return PALETTES.get(key or "", PALETTES[DEFAULT_PALETTE])


def palette_keys() -> tuple[str, ...]:
    return tuple(PALETTES)


def validate_palette(p: Palette) -> list[str]:
    """Return a list of human-readable problems (empty list = valid)."""
    errors: list[str] = []
    color_fields = [f for f in p.__dataclass_fields__ if f not in ("key", "label")]
    for name in color_fields:
        value = getattr(p, name)
        if not (isinstance(value, str) and value.startswith("#") and len(value) == 7):
            errors.append(f"{name}: expected #rrggbb, got {value!r}")
    if p.bg == p.text:
        errors.append("bg and text must differ (invisible text)")
    if p.key not in p.key.strip() or not p.key:
        errors.append("key must be non-empty")
    return errors

"""A tiny, honest i18n scaffold — QTranslator-free by design.

Full extraction (tr()-ing every label, .ts/.qm generation, a language
switcher, plural handling) is a v1.0 roadmap item; this scaffold only
gives the tray a head start and locks the shape:

- STRINGS: {lang_code: {msg_key: translation}} — flat tables, no plurals,
  no context markers.
- tr(key, code): lookup with a fallback chain (code -> "en" -> the key
  itself) that never raises and always returns something printable.
- available_langs(): the codes a future picker would offer.

"en" is complete-ish (~40 core keys); "hi" and "es" are honest partials
(18-20 keys each, correct where they exist). Consumed today only by the
tray's top transport actions (guarded in app.py); everything else stays
English until the v1.0 pass.
"""

from __future__ import annotations

from . import config

DEFAULT_LANG = config.I18N_LANG

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "play": "Play",
        "pause": "Pause",
        "play_pause": "Play / Pause",
        "next": "Next",
        "previous": "Previous",
        "shuffle": "Shuffle",
        "repeat": "Repeat",
        "queue": "Queue",
        "favorites": "Favorites",
        "playlists": "Playlists",
        "settings": "Settings",
        "themes": "Themes",
        "crossfade": "Crossfade",
        "ambient": "Ambient",
        "alarm": "Alarm",
        "stats": "Stats",
        "history": "History",
        "local": "Local",
        "plugins": "Plugins",
        "lyrics": "Lyrics",
        "theater": "Theater",
        "on": "On",
        "off": "Off",
        "search": "Search",
        "volume": "Volume",
        "mute": "Mute",
        "now_playing": "Now Playing",
        "home": "Home",
        "library": "Library",
        "discover": "Discover",
        "artists": "Artists",
        "albums": "Albums",
        "sleep_timer": "Sleep timer",
        "wake_up": "Wake-up",
        "quit": "Quit",
        "show": "Show",
        "speed": "Speed",
        "wallpaper": "Wallpaper",
        "visualizer": "Visualizer",
        "hotkeys": "Hotkeys",
    },
    # Hindi partial — transport + tray essentials.
    "hi": {
        "play": "चलाएँ",
        "pause": "रोकें",
        "next": "अगला",
        "previous": "पिछला",
        "shuffle": "शफ़ल",
        "repeat": "दोहराएँ",
        "queue": "कतार",
        "favorites": "पसंदीदा",
        "playlists": "प्लेलिस्ट",
        "settings": "सेटिंग्स",
        "history": "इतिहास",
        "search": "खोजें",
        "volume": "आवाज़",
        "mute": "मौन",
        "now_playing": "अब बज रहा है",
        "on": "चालू",
        "off": "बंद",
        "quit": "बाहर निकलें",
    },
    # Spanish partial — same essentials, slightly wider.
    "es": {
        "play": "Reproducir",
        "pause": "Pausar",
        "next": "Siguiente",
        "previous": "Anterior",
        "shuffle": "Aleatorio",
        "repeat": "Repetir",
        "queue": "Cola",
        "favorites": "Favoritos",
        "playlists": "Listas de reproducción",
        "settings": "Ajustes",
        "history": "Historial",
        "search": "Buscar",
        "volume": "Volumen",
        "mute": "Silenciar",
        "now_playing": "Reproduciendo",
        "on": "Activado",
        "off": "Desactivado",
        "quit": "Salir",
        "alarm": "Alarma",
        "stats": "Estadísticas",
    },
}


def available_langs() -> tuple[str, ...]:
    """Language codes with at least one translation, sorted."""
    return tuple(sorted(STRINGS))


def tr(key: str, code: str | None = None) -> str:
    """Translate `key`; falls back code -> "en" -> the key itself.

    Never raises: an unknown language falls to "en", an unknown key
    returns the key unchanged. `code=None` reads config.I18N_LANG at
    call time (so flipping the config flips the tray without a restart
    of the interpreter).
    """
    lang = code if code else getattr(config, "I18N_LANG", DEFAULT_LANG)
    text = STRINGS.get(lang, {}).get(key)
    if text is not None:
        return text
    fallback = STRINGS.get("en", {}).get(key)
    return fallback if fallback is not None else key

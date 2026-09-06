"""Exact presentation tokens for the desktop interface.

The default dark constants are preserved for backwards compatibility.
Use `theme_tokens("light")` or `theme_tokens("dark")` to get a full token map
for a given theme.
"""

from ls_compressor.infrastructure.config import ThemePreference

_CURRENT_THEME: ThemePreference = ThemePreference.DARK


def set_current_theme(preference: ThemePreference) -> None:
    """Set the active theme preference used by runtime helpers."""
    global _CURRENT_THEME
    _CURRENT_THEME = preference


def current_theme() -> ThemePreference:
    """Return the active theme preference."""
    return _CURRENT_THEME


# Default dark tokens
BG_APP = "#141414"
BG_SIDEBAR = "#181818"
BG_SURFACE = "#191919"
BG_SURFACE_ALT = "#1a1a1a"
BG_NAV_ACTIVE = "#232323"
BG_TABLE_HEADER = "transparent"
BORDER = "#232323"
BORDER_STRONG = "#262626"
BORDER_ROW = "#1c1c1c"
BORDER_DASHED = "#2e2e2e"
TEXT_PRIMARY = "#e4e4e4"
TEXT_SECONDARY = "#b8b8b8"
TEXT_TERTIARY = "#7a7a7a"
TEXT_MUTED = "#6a6a6a"
TEXT_DISABLED = "#5a5a5a"
ACCENT = "#b8a074"
ACCENT_ON = "#161310"
STATUS_SUCCESS = "#7fae8e"
STATUS_ERROR = "#c17b6f"
STATUS_RUNNING = "#b8a074"
PROGRESS_TRACK = "#232323"
PROGRESS_FILL_IDLE = "#4a4a4a"
PROGRESS_FILL_ACTIVE = ACCENT
FONT_UI = "Inter"
FONT_MONO = "SF Mono"
FONT_SIZE_10 = 10
FONT_SIZE_11 = 11
FONT_SIZE_12 = 12
FONT_SIZE_14 = 14
FONT_SIZE_16 = 16
FONT_WEIGHT_NORMAL = 400
FONT_WEIGHT_MEDIUM = 500
SPACE_2 = 2
SPACE_4 = 4
SPACE_6 = 6
SPACE_8 = 8
SPACE_9 = 9
SPACE_10 = 10
SPACE_11 = 11
SPACE_14 = 14
SPACE_16 = 16
SPACE_18 = 18
SPACE_20 = 20
SPACE_24 = 24
SIDEBAR_PADDING = 12
SIDEBAR_WIDTH = 180
ALGORITHM_COMBO_WIDTH = 140
HEADER_HEIGHT = 54
DROPZONE_HEIGHT = 64
TABLE_ROW_HEIGHT = 44
TABLE_HEADER_HEIGHT = 36
STAT_CARD_HEIGHT = 76
PROGRESS_BAR_HEIGHT = 3
STATUS_DOT_SIZE = 5
LOGO_SIZE = 22
LOGO_ICON_SIZE = 13
NAV_ICON_SIZE = 15
DROP_ICON_SIZE = 14
ICON_SIZE_SM = 12
BUTTON_HEIGHT = 32
COMBO_HEIGHT = 32
INPUT_HEIGHT = 32
RADIUS_SM = 2
RADIUS_MD = 6
RADIUS_LG = 8

_LIGHT: dict[str, object] = {
    "BG_APP": "#ffffff",
    "BG_SIDEBAR": "#f7f7f7",
    "BG_SURFACE": "#fafafa",
    "BG_SURFACE_ALT": "#f0f0f0",
    "BG_NAV_ACTIVE": "#eaeaea",
    "BG_TABLE_HEADER": "transparent",
    "BORDER": "#e0e0e0",
    "BORDER_STRONG": "#d0d0d0",
    "BORDER_ROW": "#eeeeee",
    "BORDER_DASHED": "#cccccc",
    "TEXT_PRIMARY": "#1a1a1a",
    "TEXT_SECONDARY": "#4a4a4a",
    "TEXT_TERTIARY": "#6a6a6a",
    "TEXT_MUTED": "#8a8a8a",
    "TEXT_DISABLED": "#aaaaaa",
    "ACCENT": "#8a6d3b",
    "ACCENT_ON": "#ffffff",
    "STATUS_SUCCESS": "#2e7d4a",
    "STATUS_ERROR": "#a94442",
    "STATUS_RUNNING": "#8a6d3b",
    "PROGRESS_TRACK": "#e0e0e0",
    "PROGRESS_FILL_IDLE": "#bdbdbd",
    "PROGRESS_FILL_ACTIVE": "#8a6d3b",
}

_DARK: dict[str, object] = {
    "BG_APP": BG_APP,
    "BG_SIDEBAR": BG_SIDEBAR,
    "BG_SURFACE": BG_SURFACE,
    "BG_SURFACE_ALT": BG_SURFACE_ALT,
    "BG_NAV_ACTIVE": BG_NAV_ACTIVE,
    "BG_TABLE_HEADER": BG_TABLE_HEADER,
    "BORDER": BORDER,
    "BORDER_STRONG": BORDER_STRONG,
    "BORDER_ROW": BORDER_ROW,
    "BORDER_DASHED": BORDER_DASHED,
    "TEXT_PRIMARY": TEXT_PRIMARY,
    "TEXT_SECONDARY": TEXT_SECONDARY,
    "TEXT_TERTIARY": TEXT_TERTIARY,
    "TEXT_MUTED": TEXT_MUTED,
    "TEXT_DISABLED": TEXT_DISABLED,
    "ACCENT": ACCENT,
    "ACCENT_ON": ACCENT_ON,
    "STATUS_SUCCESS": STATUS_SUCCESS,
    "STATUS_ERROR": STATUS_ERROR,
    "STATUS_RUNNING": STATUS_RUNNING,
    "PROGRESS_TRACK": PROGRESS_TRACK,
    "PROGRESS_FILL_IDLE": PROGRESS_FILL_IDLE,
    "PROGRESS_FILL_ACTIVE": PROGRESS_FILL_ACTIVE,
}

_THEME_TOKENS: dict[str, dict[str, object]] = {
    "dark": _DARK,
    "light": _LIGHT,
}


def theme_tokens(
    preference: ThemePreference = ThemePreference.DARK,
) -> dict[str, object]:
    """Return the full token map for the requested theme preference."""
    name = preference.value
    base: dict[str, object] = _THEME_TOKENS.get(name, _DARK)
    tokens: dict[str, object] = {
        name: value
        for name, value in globals().items()
        if not name.startswith("_") and name.isupper()
    }
    tokens.update(base)
    return tokens


def apply_theme_preference(preference: ThemePreference) -> dict[str, object]:
    """Resolve SYSTEM preference to a concrete light/dark token map."""
    if preference is ThemePreference.SYSTEM:
        return theme_tokens(ThemePreference.DARK)
    return theme_tokens(preference)


def icon_color() -> str:
    """Return the current theme's primary icon color."""
    tokens = theme_tokens(_CURRENT_THEME)
    return str(tokens.get("TEXT_PRIMARY", TEXT_PRIMARY))

"""Color tokens of the dark and light theme (also used by charts and icons)."""

from __future__ import annotations

TOKENS: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#10141c", "surface": "#171d28", "surface2": "#1f2735", "surface3": "#283246", "border": "#2c3648",
        "text": "#e7ebf3", "muted": "#8d99b1", "accent": "#5b93ff", "accent_hover": "#78a6ff", "accent_text": "#08111f",
        "danger": "#ff6b6b", "warn": "#f5b04c", "ok": "#3ecf8e", "sidebar": "#0c1017", "sidebar_text": "#b4bfd4",
        "sidebar_active": "#1c2638", "selection": "#27406e", "warn_bg": "#3a2d12", "danger_bg": "#3b1a1f", "ok_bg": "#123326",
    },
    "light": {
        "bg": "#f3f5f9", "surface": "#ffffff", "surface2": "#eef1f7", "surface3": "#e2e7f1", "border": "#d6dce9",
        "text": "#1b2333", "muted": "#64708a", "accent": "#2563eb", "accent_hover": "#1d4fd0", "accent_text": "#ffffff",
        "danger": "#d33f49", "warn": "#b86e00", "ok": "#15885a", "sidebar": "#1b2438", "sidebar_text": "#c4cde0",
        "sidebar_active": "#2b3a58", "selection": "#cfe0ff", "warn_bg": "#fff1d6", "danger_bg": "#fde4e6", "ok_bg": "#dcf5ea",
    },
}

"""System tray for JARVIS (Phase 1 foundation, pystray).

Runs pystray on a background thread with a generated placeholder icon and a
minimal menu: Open Dashboard and Quit. Wake-word, voice controls, and pause
states arrive in later phases.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

logger = logging.getLogger("jarvis.interface.tray")

ICON_SIZE = 64
ICON_BACKGROUND = (18, 22, 33, 255)
ICON_FOREGROUND = (66, 165, 245, 255)
ICON_TEXT = "J"


def _generate_icon() -> Image.Image:
    """Generate a simple placeholder tray icon (no binary assets needed)."""
    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), ICON_BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((ICON_SIZE // 3, ICON_SIZE // 5), ICON_TEXT, fill=ICON_FOREGROUND)
    return image


class SystemTray:
    """Background system-tray icon with a minimal control menu."""

    def __init__(
        self,
        on_open_dashboard: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_open_dashboard = on_open_dashboard
        self._on_quit = on_quit
        self._icon = Icon(
            "JARVIS",
            icon=_generate_icon(),
            title="JARVIS (running)",
            menu=Menu(
                MenuItem("Open Dashboard", self._open_dashboard, default=True),
                MenuItem("Quit JARVIS", self._quit),
            ),
        )
        self._thread: threading.Thread | None = None

    def _open_dashboard(self, icon: Icon, item: MenuItem) -> None:
        self._on_open_dashboard()

    def _quit(self, icon: Icon, item: MenuItem) -> None:
        logger.info("quit requested from tray")
        self._on_quit()

    def start(self) -> None:
        """Start the tray icon on a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("tray already running")
            return
        self._thread = threading.Thread(
            target=self._icon.run, name="jarvis-tray", daemon=True
        )
        self._thread.start()
        logger.info("system tray started")

    def stop(self) -> None:
        """Stop the tray icon and wait briefly for its thread."""
        if self._thread is None:
            return
        self._icon.stop()
        self._thread.join(timeout=5)
        self._thread = None
        logger.info("system tray stopped")

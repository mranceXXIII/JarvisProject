"""Window management via Win32 APIs (spec section 9).

Uses ctypes against user32 - no extra dependency. The API layer is
injectable so tests run against a fake. Only visible windows with titles
are listed; activation/size/close actions address windows by title
substring (case-insensitive).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger("jarvis.automation.windows")

SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
WM_CLOSE = 0x0010

# EnumWindows callback: BOOL CALLBACK WndEnumProc(HWND, LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)


class WindowError(RuntimeError):
    """Raised when a window operation cannot be performed."""


@dataclass(frozen=True)
class WindowInfo:
    """One visible top-level window."""

    hwnd: int
    title: str
    minimized: bool
    maximized: bool


class _RealWinApi:
    """ctypes binding to user32 (Windows only)."""

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    def enum_visible_windows(self) -> list[tuple[int, str]]:
        results: list[tuple[int, str]] = []
        user32 = self.user32
        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        enum_proc = WNDENUMPROC(
            lambda hwnd, _lparam: self._collect(user32, hwnd, results)
        )
        user32.EnumWindows(enum_proc, 0)
        return results

    @staticmethod
    def _collect(user32, hwnd, results: list[tuple[int, str]]) -> bool:
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                results.append((int(hwnd), buffer.value))
        return True

    def set_foreground(self, hwnd: int) -> bool:
        return bool(self.user32.SetForegroundWindow(hwnd))

    def show(self, hwnd: int, command: int) -> bool:
        return bool(self.user32.ShowWindow(hwnd, command))

    def close(self, hwnd: int) -> bool:
        return bool(self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self.user32.IsIconic(hwnd))

    def is_zoomed(self, hwnd: int) -> bool:
        return bool(self.user32.IsZoomed(hwnd))


class WindowManager:
    """Lists and controls desktop windows."""

    def __init__(self, api=None) -> None:
        if api is not None:
            self._api = api
        elif sys.platform == "win32":
            self._api = _RealWinApi()
        else:
            self._api = None

    @property
    def available(self) -> bool:
        return self._api is not None

    def list_windows(self, limit: int = 50) -> list[WindowInfo]:
        """Visible windows with titles."""
        if self._api is None:
            return []
        windows: list[WindowInfo] = []
        for hwnd, title in self._api.enum_visible_windows():
            windows.append(
                WindowInfo(
                    hwnd=hwnd,
                    title=title,
                    minimized=self._api.is_iconic(hwnd),
                    maximized=self._api.is_zoomed(hwnd),
                )
            )
            if len(windows) >= limit:
                break
        return windows

    def _find(self, title: str) -> WindowInfo:
        """Find a window by case-insensitive substring match."""
        needle = title.strip().lower()
        matches = [
            w for w in self.list_windows(limit=200) if needle in w.title.lower()
        ]
        if not matches:
            raise WindowError(f"no visible window matches '{title}'")
        return matches[0]

    def activate(self, title: str) -> str:
        window = self._find(title)
        if self._api.set_foreground(window.hwnd):
            return f"activated '{window.title}'"
        raise WindowError(f"could not activate '{window.title}'")

    def minimize(self, title: str) -> str:
        window = self._find(title)
        if self._api.show(window.hwnd, SW_MINIMIZE):
            return f"minimized '{window.title}'"
        raise WindowError(f"could not minimize '{window.title}'")

    def maximize(self, title: str) -> str:
        window = self._find(title)
        if self._api.show(window.hwnd, SW_MAXIMIZE):
            return f"maximized '{window.title}'"
        raise WindowError(f"could not maximize '{window.title}'")

    def restore(self, title: str) -> str:
        window = self._find(title)
        if self._api.show(window.hwnd, SW_RESTORE):
            return f"restored '{window.title}'"
        raise WindowError(f"could not restore '{window.title}'")

    def close(self, title: str) -> str:
        """Politely close a window (WM_CLOSE; the app may prompt to save)."""
        window = self._find(title)
        if self._api.close(window.hwnd):
            return f"close request sent to '{window.title}'"
        raise WindowError(f"could not close '{window.title}'")

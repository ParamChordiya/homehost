"""HomeHost TUI screens."""

from __future__ import annotations

from homehost.tui.screens.manage import ManageScreen
from homehost.tui.screens.setup import SetupScreen
from homehost.tui.screens.status import StatusScreen
from homehost.tui.screens.uninstall import UninstallScreen
from homehost.tui.screens.welcome import WelcomeScreen

__all__ = [
    "WelcomeScreen",
    "SetupScreen",
    "StatusScreen",
    "ManageScreen",
    "UninstallScreen",
]

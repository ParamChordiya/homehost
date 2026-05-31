"""HomeHost web dashboard — runs at http://localhost:9111."""

from homehost.dashboard.server import DashboardServer, start_dashboard_in_background

__all__ = ["DashboardServer", "start_dashboard_in_background"]

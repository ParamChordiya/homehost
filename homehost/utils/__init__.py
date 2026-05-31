"""HomeHost utility modules."""

from homehost.utils.logger import HomeHostLogger, get_logger, setup_logging
from homehost.utils.network import (
    check_internet,
    check_port_externally_accessible,
    find_free_port,
    format_bytes,
    get_all_interfaces,
    get_local_ip,
    get_public_ip,
    is_port_in_use,
    wait_for_port,
)
from homehost.utils.platform import (
    get_arch,
    get_home_dir,
    get_os,
    get_os_version,
    get_system_info_string,
    get_temp_dir,
    is_admin,
    is_linux,
    is_macos,
    is_windows,
    open_file_manager,
    open_in_browser,
    run_elevated,
)
from homehost.utils.updater import (
    UpdateInfo,
    check_for_updates,
    perform_update,
    should_check_for_updates,
)

__all__ = [
    # logger
    "setup_logging",
    "get_logger",
    "HomeHostLogger",
    # network
    "get_local_ip",
    "get_all_interfaces",
    "is_port_in_use",
    "find_free_port",
    "check_internet",
    "wait_for_port",
    "get_public_ip",
    "format_bytes",
    "check_port_externally_accessible",
    # platform
    "get_os",
    "get_arch",
    "is_macos",
    "is_windows",
    "is_linux",
    "get_os_version",
    "open_in_browser",
    "open_file_manager",
    "get_home_dir",
    "get_temp_dir",
    "is_admin",
    "run_elevated",
    "get_system_info_string",
    # updater
    "UpdateInfo",
    "check_for_updates",
    "perform_update",
    "should_check_for_updates",
]

"""Network layer: local IP detection, Cloudflare tunnels, firewall, DNS, SSL."""

from homehost.network.dns import (
    check_dns_resolution,
    format_dns_instructions,
    generate_random_subdomain,
    get_public_ip,
    validate_subdomain,
)
from homehost.network.firewall import FirewallManager
from homehost.network.local import (
    check_lan_connectivity,
    format_local_url,
    generate_qr_code,
    get_all_local_ips,
    get_local_ip,
    is_private_ip,
    print_qr_code,
    register_mdns,
    unregister_mdns,
)
from homehost.network.ssl import check_ssl_cert, days_until_expiry
from homehost.network.tunnel import TunnelInfo, TunnelManager

__all__ = [
    # local
    "get_local_ip",
    "get_all_local_ips",
    "generate_qr_code",
    "print_qr_code",
    "register_mdns",
    "unregister_mdns",
    "check_lan_connectivity",
    "format_local_url",
    "is_private_ip",
    # tunnel
    "TunnelInfo",
    "TunnelManager",
    # firewall
    "FirewallManager",
    # dns
    "check_dns_resolution",
    "get_public_ip",
    "validate_subdomain",
    "generate_random_subdomain",
    "format_dns_instructions",
    # ssl
    "check_ssl_cert",
    "days_until_expiry",
]

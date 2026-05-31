"""DNS utilities and subdomain helpers for HomeHost."""

from __future__ import annotations

import logging
import random
import re
import socket
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Word lists for random subdomain generation
# ---------------------------------------------------------------------------
_ADJECTIVES = [
    "amber", "azure", "breezy", "bright", "calm", "cherry", "cloudy", "cool",
    "crisp", "dawn", "deep", "dusk", "dusty", "early", "east", "ember",
    "fern", "flint", "foggy", "fresh", "frosty", "gentle", "golden", "grand",
    "green", "grey", "hazy", "hollow", "jade", "keen", "lake", "lemon",
    "light", "lively", "lunar", "maple", "mist", "misty", "mossy", "narrow",
    "noble", "north", "ocean", "olive", "open", "pale", "pearl", "pine",
    "plain", "quiet", "rapid", "rainy", "red", "rocky", "rosy", "royal",
    "rustic", "sandy", "serene", "shady", "silent", "silver", "sleek",
    "slim", "slow", "snowy", "soft", "solar", "south", "still", "stone",
    "stormy", "summer", "sunny", "swift", "tall", "teal", "tiny", "warm",
    "west", "white", "wild", "windy", "winter", "wise", "wooden", "yellow",
]

_NOUNS = [
    "alley", "arch", "atlas", "bay", "beacon", "birch", "brook", "canyon",
    "cedar", "cliff", "cloud", "cove", "creek", "crest", "delta", "den",
    "dune", "elm", "falls", "fen", "field", "flare", "fjord", "flint",
    "forge", "gate", "glade", "glen", "gorge", "grove", "haven", "heath",
    "hill", "hollow", "horn", "inlet", "isle", "keep", "knoll", "lake",
    "lane", "larch", "ledge", "light", "loch", "loop", "marsh", "meadow",
    "mire", "moor", "moss", "mount", "oak", "orbit", "pass", "path",
    "peak", "pier", "pine", "plain", "pond", "pool", "port", "post",
    "quay", "range", "rapid", "ravine", "reef", "ridge", "rift", "rise",
    "river", "rock", "route", "sand", "shelf", "shore", "sill", "slope",
    "sound", "span", "spit", "spring", "stem", "step", "stone", "storm",
    "strand", "stream", "summit", "swale", "torch", "trail", "vale", "valley",
    "vault", "veil", "view", "wake", "wall", "wave", "well", "wood",
]

_CITIES = [
    "accra", "alice", "amman", "anchorage", "apia", "athens", "baku",
    "bali", "bern", "berlin", "bogota", "brasilia", "bruges", "cairo",
    "capetown", "cebu", "chiang-mai", "dubai", "dublin", "edinburgh",
    "florence", "genoa", "ghent", "hamilton", "hanoi", "havana", "ibiza",
    "jakarta", "kampala", "kathmandu", "kigali", "kingston", "kyoto",
    "lahore", "lima", "lisbon", "lombok", "lome", "lugano", "lviv",
    "madeira", "malaga", "malta", "mandalay", "maputo", "marrakesh",
    "milan", "minsk", "monaco", "montevideo", "moscow", "muscat", "naples",
    "nassau", "nairobi", "oslo", "palermo", "palma", "paphos", "paris",
    "perth", "podgorica", "prague", "pristina", "puebla", "reykjavik",
    "riga", "rotterdam", "saigon", "salzburg", "sarajevo", "seville",
    "skopje", "sofia", "split", "stockholm", "suva", "sydney", "taipei",
    "tallinn", "tashkent", "tbilisi", "tehran", "tirana", "tokyo", "toronto",
    "trieste", "tripoli", "tunis", "turin", "ulaanbaatar", "valletta",
    "vienna", "vilnius", "warsaw", "zagreb", "zurich",
]

# Subdomain validation pattern (lowercase alphanumeric + hyphens, no leading/trailing)
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def check_dns_resolution(hostname: str) -> bool:
    """Return ``True`` if *hostname* resolves to at least one IP address.

    Uses ``socket.getaddrinfo`` with a 5-second timeout (via a separate thread
    because Python's stdlib DNS resolution is blocking).
    """
    import concurrent.futures

    def _resolve() -> bool:
        try:
            results = socket.getaddrinfo(hostname, None)
            return len(results) > 0
        except (socket.gaierror, socket.herror, OSError):
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_resolve)
        try:
            return future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            log.debug("DNS resolution timeout for %r", hostname)
            return False


def get_public_ip() -> str:
    """Fetch the machine's public IP from ``https://api.ipify.org``.

    Returns the IP string on success, or ``''`` on any error.  Timeout is 5 s.
    """
    url = "https://api.ipify.org"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "homehost/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            ip = resp.read().decode("ascii").strip()
            log.debug("Public IP: %s", ip)
            return ip
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.debug("Could not fetch public IP: %s", exc)
        return ""


def validate_subdomain(name: str) -> tuple[bool, str]:
    """Validate a subdomain name.

    Rules:
    - Lowercase alphanumeric characters and hyphens only
    - Length: 3–63 characters
    - Must not start or end with a hyphen

    Returns ``(True, "")`` if valid, or ``(False, error_message)`` if not.
    """
    if not name:
        return False, "Subdomain must not be empty."

    if len(name) < 3:
        return False, f"Subdomain too short ({len(name)} chars); minimum is 3."

    if len(name) > 63:
        return False, f"Subdomain too long ({len(name)} chars); maximum is 63."

    if not re.match(r"^[a-z0-9-]+$", name):
        return False, (
            "Subdomain may only contain lowercase letters, digits, and hyphens. "
            f"Got: {name!r}"
        )

    if name.startswith("-"):
        return False, "Subdomain must not start with a hyphen."

    if name.endswith("-"):
        return False, "Subdomain must not end with a hyphen."

    if "--" in name and not name.startswith("xn--"):
        # Allow internationalized domain name (IDN) prefixes but warn on
        # bare double-hyphens that are not IDN-encoded.
        log.debug("Subdomain %r contains consecutive hyphens (unusual)", name)

    return True, ""


def generate_random_subdomain(prefix: str = "") -> str:
    """Generate a random subdomain in the form ``<adj>-<noun>-<city>``.

    If *prefix* is supplied it is prepended with a trailing hyphen, e.g.
    ``"myapp-sunset-maple-tokyo"``.

    The result is guaranteed to pass :func:`validate_subdomain`.
    """
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    city = random.choice(_CITIES)

    parts = [adj, noun, city]
    if prefix:
        # Sanitize prefix: lowercase, replace non-alphanumeric with hyphen
        safe_prefix = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")
        if safe_prefix:
            parts.insert(0, safe_prefix)

    candidate = "-".join(parts)

    # Trim to 63 chars if the prefix made it too long (preserve suffix)
    if len(candidate) > 63:
        suffix = f"-{noun}-{city}"
        max_prefix = 63 - len(suffix)
        candidate = candidate[:max_prefix] + suffix

    # Ensure it passes validation (defensive)
    candidate = candidate.strip("-")
    ok, _ = validate_subdomain(candidate)
    if not ok:
        # Absolute fallback: pure random chars
        candidate = f"homehost-{random.randint(10000, 99999)}"

    return candidate


def format_dns_instructions(domain: str, tunnel_url: str) -> str:
    """Return formatted step-by-step instructions for pointing *domain* to Cloudflare.

    *tunnel_url* is the ``trycloudflare.com`` (or named tunnel) URL that the
    user needs to reference.

    Returns a plain-text multi-line string suitable for display in a terminal
    or Rich panel.
    """
    # Extract the hostname from the tunnel URL (strip scheme)
    tunnel_host = tunnel_url.removeprefix("https://").removeprefix("http://").split("/")[0]

    instructions = f"""
To point  {domain}  to your HomeHost tunnel, follow these steps:

1. Log in to your DNS provider (e.g. Cloudflare, Namecheap, Route 53, GoDaddy).

2. Navigate to the DNS management page for  {domain}.

3. Add a CNAME record:
     Name / Host  →  {domain if "." in domain.split(".")[0] else "@"}
     Target / Value  →  {tunnel_host}
     TTL  →  Auto (or 300 seconds)

   If your DNS provider does not support a root-domain CNAME ("CNAME flattening"),
   use an ALIAS / ANAME record pointing to the same target.

4. Wait for DNS propagation (typically 1–5 minutes with Cloudflare, up to 48 h
   with other providers).

5. Verify:
     dig {domain} CNAME +short
     curl -I https://{domain}

Notes:
  • Cloudflare Tunnel handles HTTPS automatically — no SSL certificate setup needed.
  • If you manage DNS through Cloudflare, enable the orange-cloud (proxy) to
    benefit from DDoS protection and edge caching.
  • Tunnel URL for reference: {tunnel_url}
""".strip()

    return instructions

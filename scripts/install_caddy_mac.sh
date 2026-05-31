#!/usr/bin/env bash
# HomeHost — Install Caddy on macOS
# Usage: bash install_caddy_mac.sh [--force]
#
# Strategy:
#   1. Check for an existing Caddy installation
#   2. Try Homebrew (brew install caddy)
#   3. Fall back to direct binary download from GitHub Releases
#
# The binary ends up at:
#   - /opt/homebrew/bin/caddy  (Homebrew, Apple Silicon)
#   - /usr/local/bin/caddy     (Homebrew, Intel)
#   - ~/.homehost/bin/caddy    (direct download)

set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Colour

info()    { printf "${BLUE}[homehost]${NC} %s\n" "$*"; }
success() { printf "${GREEN}[homehost]${NC} %s\n" "$*"; }
warn()    { printf "${YELLOW}[homehost] WARNING:${NC} %s\n" "$*"; }
die()     { printf "${RED}[homehost] ERROR:${NC} %s\n" "$*" >&2; exit 1; }

# ── Configuration ──────────────────────────────────────────────────────────────
HOMEHOST_BIN="${HOME}/.homehost/bin"
CADDY_GITHUB_API="https://api.github.com/repos/caddyserver/caddy/releases/latest"
FORCE="${1:-}"

# ── Helpers ────────────────────────────────────────────────────────────────────

command_exists() { command -v "$1" &>/dev/null; }

ensure_bin_dir() {
    mkdir -p "${HOMEHOST_BIN}"
}

verify_caddy() {
    local path="${1}"
    if "${path}" version &>/dev/null; then
        "${path}" version | head -1
        return 0
    fi
    return 1
}

detect_arch() {
    local arch
    arch="$(uname -m)"
    case "${arch}" in
        arm64 | aarch64) echo "arm64" ;;
        x86_64)          echo "amd64" ;;
        *)               die "Unsupported architecture: ${arch}" ;;
    esac
}

fetch_latest_tag() {
    local tag
    if command_exists curl; then
        tag="$(curl -fsSL "${CADDY_GITHUB_API}" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"
    elif command_exists wget; then
        tag="$(wget -qO- "${CADDY_GITHUB_API}" | grep '"tag_name"' | head -1 | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"
    else
        die "Neither curl nor wget found. Install one and retry."
    fi
    echo "${tag}"
}

download_file() {
    local url="${1}" dest="${2}"
    info "Downloading ${url}"
    if command_exists curl; then
        curl -fL --progress-bar -o "${dest}" "${url}"
    elif command_exists wget; then
        wget -q --show-progress -O "${dest}" "${url}"
    else
        die "Neither curl nor wget found."
    fi
}

# ── Step 1: Check existing installation ───────────────────────────────────────

check_existing() {
    if [[ "${FORCE}" == "--force" ]]; then
        info "--force flag set; skipping existing installation check."
        return 1
    fi

    # Check ~/.homehost/bin first
    local local_caddy="${HOMEHOST_BIN}/caddy"
    if [[ -x "${local_caddy}" ]]; then
        local version
        version="$(verify_caddy "${local_caddy}" 2>/dev/null || true)"
        if [[ -n "${version}" ]]; then
            success "Caddy already installed at ${local_caddy} (${version})"
            return 0
        fi
    fi

    if command_exists caddy; then
        local caddy_path version
        caddy_path="$(command -v caddy)"
        version="$(verify_caddy "${caddy_path}" 2>/dev/null || true)"
        if [[ -n "${version}" ]]; then
            success "Caddy already installed at ${caddy_path} (${version})"
            return 0
        fi
    fi

    return 1
}

# ── Step 2: Install via Homebrew ───────────────────────────────────────────────

install_via_brew() {
    if ! command_exists brew; then
        warn "Homebrew not found."
        return 1
    fi

    info "Installing Caddy via Homebrew…"
    if brew install caddy; then
        local caddy_path version
        caddy_path="$(command -v caddy)"
        version="$(verify_caddy "${caddy_path}")"
        success "Caddy ${version} installed via Homebrew at ${caddy_path}"
        print_path_hint "${caddy_path}"
        return 0
    else
        warn "brew install caddy failed."
        return 1
    fi
}

# ── Step 3: Direct binary download ────────────────────────────────────────────

install_direct() {
    ensure_bin_dir

    info "Fetching latest Caddy release info from GitHub…"
    local tag
    tag="$(fetch_latest_tag)"
    [[ -z "${tag}" ]] && die "Could not determine latest Caddy version from GitHub API."

    local version="${tag#v}"   # strip leading 'v'
    local arch
    arch="$(detect_arch)"
    local archive_name="caddy_${version}_mac_${arch}.tar.gz"
    local download_url="https://github.com/caddyserver/caddy/releases/download/${tag}/${archive_name}"

    local tmpdir
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "${tmpdir}"' EXIT

    local archive_path="${tmpdir}/${archive_name}"
    download_file "${download_url}" "${archive_path}"

    info "Extracting ${archive_name}…"
    tar -xzf "${archive_path}" -C "${tmpdir}"

    local extracted="${tmpdir}/caddy"
    [[ -f "${extracted}" ]] || die "caddy binary not found after extraction. Archive contents: $(ls "${tmpdir}")"

    local dest="${HOMEHOST_BIN}/caddy"
    cp "${extracted}" "${dest}"
    chmod +x "${dest}"

    local version_str
    version_str="$(verify_caddy "${dest}")"
    [[ -n "${version_str}" ]] || die "Installed caddy binary at ${dest} failed to execute."

    success "Caddy ${version_str} installed at ${dest}"
    print_path_hint "${dest}"
}

# ── Path hint ─────────────────────────────────────────────────────────────────

print_path_hint() {
    local path="${1}"
    local dir
    dir="$(dirname "${path}")"

    # Check if the directory is already on PATH
    if echo ":${PATH}:" | grep -q ":${dir}:"; then
        return
    fi

    warn "${dir} is not on your PATH."
    printf "\n  Add it by appending the following to your shell config:\n\n"
    if [[ "${SHELL}" == *"zsh"* ]]; then
        printf "    echo 'export PATH=\"%s:\$PATH\"' >> ~/.zshrc && source ~/.zshrc\n\n" "${dir}"
    else
        printf "    echo 'export PATH=\"%s:\$PATH\"' >> ~/.bashrc && source ~/.bashrc\n\n" "${dir}"
    fi
}

# ── Main ───────────────────────────────────────────────────────────────────────

main() {
    info "HomeHost — Caddy installer (macOS)"
    info "====================================="

    # Require macOS
    if [[ "$(uname -s)" != "Darwin" ]]; then
        die "This script is for macOS only. For Windows, use install_caddy_win.ps1."
    fi

    check_existing && exit 0

    info "Caddy not found (or --force). Proceeding with installation…"

    if install_via_brew; then
        exit 0
    fi

    info "Falling back to direct binary download…"
    install_direct
}

main "$@"

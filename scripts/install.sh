#!/usr/bin/env bash
# arc LXC bootstrap -- run as root inside the container, then switch to arc user.
# Usage: bash install.sh [--arc-repo <url>] [--workspace-dir <path>]
set -euo pipefail

ARC_REPO="${ARC_REPO:-https://github.com/eknorr/arc.git}"
ARC_USER="${ARC_USER:-arc}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
ARC_DIR="/opt/arc"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { echo "[arc install] $*"; }
error() { echo "[arc install] ERROR: $*" >&2; exit 1; }

require_root() {
    [ "$(id -u)" -eq 0 ] || error "Run as root."
}

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------

install_system_deps() {
    info "Installing system dependencies..."
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        git curl ca-certificates iptables \
        gnupg lsb-release
}

install_nodejs() {
    info "Installing Node.js 22..."
    if command -v node &>/dev/null && node --version | grep -q "^v2[2-9]"; then
        info "Node.js $(node --version) already installed."
        return
    fi
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs
    info "Node.js $(node --version) installed."
}

# ---------------------------------------------------------------------------
# arc user
# ---------------------------------------------------------------------------

create_arc_user() {
    if id "$ARC_USER" &>/dev/null; then
        info "User '$ARC_USER' already exists."
        return
    fi
    info "Creating user '$ARC_USER'..."
    useradd -m -s /bin/bash "$ARC_USER"
}

# ---------------------------------------------------------------------------
# Workspace directories
# ---------------------------------------------------------------------------

setup_workspace() {
    info "Setting up workspace at $WORKSPACE_DIR..."
    mkdir -p "$WORKSPACE_DIR"
    chown -R "$ARC_USER:$ARC_USER" "$WORKSPACE_DIR"
}

# ---------------------------------------------------------------------------
# arc installation (run as arc user)
# ---------------------------------------------------------------------------

install_arc_as_user() {
    info "Installing arc and dependencies as $ARC_USER..."
    su - "$ARC_USER" bash -s << EOF
set -euo pipefail

# Claude Code CLI
if ! command -v claude &>/dev/null; then
    echo "Installing Claude Code..."
    curl -fsSL https://claude.ai/install.sh | bash
fi

# acpx
if ! command -v acpx &>/dev/null; then
    echo "Installing acpx..."
    npm install -g acpx@latest
fi

# arc
if [ ! -d "$ARC_DIR" ]; then
    git clone "$ARC_REPO" "$ARC_DIR"
fi
cd "$ARC_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --quiet -e ".[dev]"

# Make arc available on PATH
mkdir -p ~/.local/bin
ln -sf "$ARC_DIR/venv/bin/arc" ~/.local/bin/arc

# ~/.arc directory
mkdir -p ~/.arc/agents ~/.arc/cron ~/.arc/logs
touch ~/.arc/.env
chmod 600 ~/.arc/.env

echo "arc $(arc version 2>/dev/null || echo 'installed') ready."
EOF
}

# ---------------------------------------------------------------------------
# Network isolation (iptables)
# ---------------------------------------------------------------------------

apply_network_rules() {
    info "Applying iptables network isolation..."

    # Flush existing
    iptables -F OUTPUT 2>/dev/null || true

    # Allow loopback
    iptables -A OUTPUT -o lo -j ACCEPT

    # Allow established connections
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

    # Allow DNS
    iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
    iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

    # Allow Anthropic API (Claude Code)
    iptables -A OUTPUT -d api.anthropic.com -j ACCEPT
    iptables -A OUTPUT -d claude.ai -j ACCEPT

    # Allow GitHub (git pull/push)
    iptables -A OUTPUT -d github.com -j ACCEPT
    iptables -A OUTPUT -d objects.githubusercontent.com -j ACCEPT

    # Allow Discord
    iptables -A OUTPUT -d discord.com -j ACCEPT
    iptables -A OUTPUT -d gateway.discord.gg -j ACCEPT
    iptables -A OUTPUT -d cdn.discordapp.com -j ACCEPT

    # Allow local Ollama (adjust IP as needed)
    # iptables -A OUTPUT -d 10.20.0.233 -p tcp --dport 11434 -j ACCEPT

    # Block everything else
    iptables -A OUTPUT -j DROP

    # Persist rules
    if command -v iptables-save &>/dev/null; then
        iptables-save > /etc/iptables.rules
        cat > /etc/network/if-pre-up.d/iptables << 'IPRULES'
#!/bin/sh
iptables-restore < /etc/iptables.rules
IPRULES
        chmod +x /etc/network/if-pre-up.d/iptables
    fi

    info "Network isolation applied."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

require_root

info "Starting arc installation..."
install_system_deps
install_nodejs
create_arc_user
setup_workspace
install_arc_as_user

read -rp "Apply iptables network isolation? [y/N] " apply_net
if [[ "${apply_net,,}" == "y" ]]; then
    apply_network_rules
fi

info ""
info "Installation complete."
info ""
info "Next steps:"
info "  1. su - $ARC_USER"
info "  2. claude auth login          # authenticate Claude Code"
info "  3. arc setup                  # configure agents and Discord"
info "  4. arc daemon start           # start the daemon"
info "  5. arc daemon install         # generate systemd unit (optional)"

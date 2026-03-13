#!/usr/bin/env bash
# install.sh — Install smart_cli.py as a system-wide 'smart' command
# Usage: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PATH="/usr/local/bin/smart"
SCRIPT="$SCRIPT_DIR/smart_cli.py"

echo ""
echo "  Smart CLI Installer"
echo "  ───────────────────"

# Copy script
if cp "$SCRIPT" "$INSTALL_PATH" 2>/dev/null; then
    chmod +x "$INSTALL_PATH"
    echo "  ✓ Installed to $INSTALL_PATH"
else
    echo "  ⚠  Need sudo to install to /usr/local/bin"
    sudo cp "$SCRIPT" "$INSTALL_PATH"
    sudo chmod +x "$INSTALL_PATH"
    echo "  ✓ Installed to $INSTALL_PATH (with sudo)"
fi

# Optional: set API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "  To enable AI features, add this to your ~/.bashrc or ~/.zshrc:"
    echo "    export ANTHROPIC_API_KEY='your-key-here'"
    echo ""
    echo "  Get a key at https://console.anthropic.com"
fi

echo ""
echo "  ✓ Done! Run 'smart' to start Smart CLI."
echo ""
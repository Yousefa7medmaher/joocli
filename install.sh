#!/usr/bin/env bash
# install.sh — Install joo_cli.py as a system-wide 'joo' command
# Usage: bash install.sh
# Supports: Linux, macOS, WSL2

set -e

# ─── Colors ───────────────────────────────────────────────────────────────────
R="\033[0m"
BOLD="\033[1m"
DIM="\033[2m"
CYAN="\033[96m"
GREEN="\033[92m"
YELLOW="\033[93m"
RED="\033[91m"
BLUE="\033[94m"

c() { printf "${!2}%s${R}" "$1"; }

# ─── Banner ───────────────────────────────────────────────────────────────────
echo ""
printf "${CYAN}${BOLD}"
cat << 'EOF'
     ██╗ ██████╗  ██████╗      ██████╗██╗     ██╗
     ██║██╔═══██╗██╔═══██╗    ██╔════╝██║     ██║
     ██║██║   ██║██║   ██║    ██║     ██║     ██║
██   ██║██║   ██║██║   ██║    ██║     ██║     ██║
╚█████╔╝╚██████╔╝╚██████╔╝    ╚██████╗███████╗██║
 ╚════╝  ╚═════╝  ╚═════╝      ╚═════╝╚══════╝╚═╝
EOF
printf "${R}"
printf "${YELLOW}  Smart Terminal Assistant  v4.0  —  Installer${R}\n"
printf "${DIM}  ─────────────────────────────────────────────${R}\n"
echo ""

# ─── Config ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PATH="/usr/local/bin/joo"
SCRIPT="$SCRIPT_DIR/joo_cli.py"
CONFIG_FILE="$HOME/.joocli_config.json"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=8

# ─── Step 1: Check source file ────────────────────────────────────────────────
printf "  ${BOLD}[1/5]${R} Checking source file...\n"

if [ ! -f "$SCRIPT" ]; then
    printf "  ${RED}✗  joo_cli.py not found in: $SCRIPT_DIR${R}\n"
    printf "  ${DIM}    Make sure install.sh is in the same folder as joo_cli.py${R}\n"
    echo ""
    exit 1
fi
printf "  ${GREEN}✓  Found:${R} ${DIM}$SCRIPT${R}\n"

# ─── Step 2: Fix Windows CRLF (WSL safety) ───────────────────────────────────
printf "  ${BOLD}[2/5]${R} Checking line endings...\n"

if file "$SCRIPT" 2>/dev/null | grep -q "CRLF"; then
    printf "  ${YELLOW}⚠  CRLF detected — converting to LF...${R}\n"
    sed -i 's/\r//' "$SCRIPT"
    printf "  ${GREEN}✓  Line endings fixed${R}\n"
elif command -v python3 &>/dev/null && python3 -c "
import sys
data = open('$SCRIPT', 'rb').read()
sys.exit(0 if b'\r\n' in data else 1)
" 2>/dev/null; then
    sed -i 's/\r//' "$SCRIPT" 2>/dev/null || sed -i '' 's/\r//' "$SCRIPT" 2>/dev/null || true
    printf "  ${GREEN}✓  CRLF converted to LF${R}\n"
else
    printf "  ${GREEN}✓  Line endings OK${R}\n"
fi

# ─── Step 3: Check Python version ────────────────────────────────────────────
printf "  ${BOLD}[3/5]${R} Checking Python...\n"

PYTHON_BIN=""
for candidate in python3 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge "$MIN_PYTHON_MAJOR" ] && [ "$minor" -ge "$MIN_PYTHON_MINOR" ]; then
            PYTHON_BIN=$(command -v "$candidate")
            printf "  ${GREEN}✓  Python $version${R} ${DIM}($PYTHON_BIN)${R}\n"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    printf "  ${RED}✗  Python 3.8+ not found.${R}\n"
    printf "  ${DIM}    Install it:${R}\n"
    printf "  ${DIM}      Ubuntu/Debian:  sudo apt install python3${R}\n"
    printf "  ${DIM}      macOS:          brew install python3${R}\n"
    echo ""
    exit 1
fi

# Patch shebang line to use the found python3
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "1s|.*|#!$PYTHON_BIN|" "$SCRIPT" 2>/dev/null || true
else
    sed -i "1s|.*|#!$PYTHON_BIN|" "$SCRIPT" 2>/dev/null || true
fi

# ─── Step 4: Install binary ──────────────────────────────────────────────────
printf "  ${BOLD}[4/5]${R} Installing to $INSTALL_PATH...\n"

# Check if already installed
UPGRADED=0
if [ -f "$INSTALL_PATH" ]; then
    OLD_VER=$(grep -m1 "v[0-9]\+\.[0-9]\+" "$INSTALL_PATH" 2>/dev/null | grep -o "v[0-9]\+\.[0-9]\+" | head -1 || echo "unknown")
    UPGRADED=1
fi

if cp "$SCRIPT" "$INSTALL_PATH" 2>/dev/null; then
    chmod +x "$INSTALL_PATH"
    if [ "$UPGRADED" -eq 1 ]; then
        printf "  ${GREEN}✓  Upgraded${R} ${DIM}($OLD_VER → v4.0)${R} ${DIM}→ $INSTALL_PATH${R}\n"
    else
        printf "  ${GREEN}✓  Installed${R} ${DIM}→ $INSTALL_PATH${R}\n"
    fi
else
    printf "  ${YELLOW}⚠  Need sudo to write to /usr/local/bin${R}\n"
    sudo cp "$SCRIPT" "$INSTALL_PATH"
    sudo chmod +x "$INSTALL_PATH"
    if [ "$UPGRADED" -eq 1 ]; then
        printf "  ${GREEN}✓  Upgraded${R} ${DIM}($OLD_VER → v4.0) with sudo → $INSTALL_PATH${R}\n"
    else
        printf "  ${GREEN}✓  Installed${R} ${DIM}with sudo → $INSTALL_PATH${R}\n"
    fi
fi

# ─── Step 5: AI provider setup ────────────────────────────────────────────────
printf "  ${BOLD}[5/5]${R} Checking AI configuration...\n"

# Count how many keys are already set
KEYS_FOUND=0
KEY_NAMES=""

check_key() {
    local name="$1" envvar="$2" prefix="$3"
    local val="${!envvar}"
    # Also check config file
    if [ -z "$val" ] && [ -f "$CONFIG_FILE" ]; then
        val=$(python3 -c "
import json, sys
try:
    d = json.load(open('$CONFIG_FILE'))
    print(d.get('keys', {}).get('$name', ''))
except: pass
" 2>/dev/null)
    fi
    if [ -n "$val" ] && [[ "$val" == ${prefix}* ]]; then
        printf "  ${GREEN}✓  $name key detected${R} ${DIM}(${val:0:6}...)${R}\n"
        KEYS_FOUND=$((KEYS_FOUND + 1))
        KEY_NAMES="$KEY_NAMES $name"
        return 0
    fi
    return 1
}

check_key "groq"    "GROQ_API_KEY"       "gsk_"   || true
check_key "claude"  "ANTHROPIC_API_KEY"  "sk-ant-" || true
check_key "chatgpt" "OPENAI_API_KEY"     "sk-"    || true
check_key "gemini"  "GEMINI_API_KEY"     "AIza"   || true

if [ "$KEYS_FOUND" -eq 0 ]; then
    printf "  ${YELLOW}⚠  No AI keys found.${R}\n"
    echo ""
    printf "  ${BOLD}  Add at least one key to enable AI features:${R}\n"
    echo ""
    printf "  ${DIM}  # Option A — inside joo (saved to ~/.joocli_config.json):${R}\n"
    printf "  ${CYAN}    :ai key groq    gsk_xxxxxxxxxxxx${R}\n"
    printf "  ${CYAN}    :ai key claude  sk-ant-xxxxxxxxxxxx${R}\n"
    echo ""
    printf "  ${DIM}  # Option B — environment variable (add to ~/.bashrc or ~/.zshrc):${R}\n"
    printf "  ${CYAN}    export GROQ_API_KEY='gsk_xxxxxxxxxxxx'${R}      ${DIM}# Free at console.groq.com${R}\n"
    printf "  ${CYAN}    export ANTHROPIC_API_KEY='sk-ant-xxx'${R}       ${DIM}# console.anthropic.com${R}\n"
    printf "  ${CYAN}    export OPENAI_API_KEY='sk-xxx'${R}              ${DIM}# platform.openai.com${R}\n"
    printf "  ${CYAN}    export GEMINI_API_KEY='AIzaxxxxxxxx'${R}        ${DIM}# aistudio.google.com${R}\n"
    echo ""
    printf "  ${DIM}  Key prefixes:  groq=gsk_  claude=sk-ant-  chatgpt=sk-  gemini=AIza${R}\n"
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
printf "${DIM}  ─────────────────────────────────────────────${R}\n"
printf "  ${GREEN}${BOLD}✓  Installation complete!${R}\n"
echo ""
printf "  ${BOLD}  Start:${R}        ${CYAN}joo${R}\n"
printf "  ${BOLD}  AI status:${R}    ${CYAN}joo :ai status${R}\n"
printf "  ${BOLD}  Help:${R}         ${CYAN}joo :help${R}\n"
printf "  ${BOLD}  Ping test:${R}    ${CYAN}joo :ping 8.8.8.8${R}\n"
echo ""

# ─── Verify it runs ───────────────────────────────────────────────────────────
if command -v joo &>/dev/null; then
    printf "  ${DIM}  Verifying...${R} "
    if joo exit &>/dev/null; then
        printf "${GREEN}joo is working ✓${R}\n"
    else
        printf "${YELLOW}installed but verify manually${R}\n"
    fi
fi
echo ""
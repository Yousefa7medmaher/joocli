#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JooCLI — Smart Terminal Assistant
Autocomplete · AI Troubleshooting · Docker Inspector · Network Tools

Usage:
    python3 joo_cli.py

Requires:
    - Python 3.8+  (stdlib only — no pip needed)
    - One or more AI API keys (optional, for AI features):
        ANTHROPIC_API_KEY  → Claude (claude-sonnet-4-20250514)
        OPENAI_API_KEY     → ChatGPT (gpt-4o)
        GROQ_API_KEY       → Groq / LLaMA (llama-3.3-70b-versatile)
        GEMINI_API_KEY     → Google Gemini (gemini-1.5-flash)
"""

import os
import re
import json
import readline
import subprocess
import urllib.request
import urllib.error
import socket
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
HISTORY_FILE = Path.home() / ".joocli_history"
LOG_FILE     = Path.home() / ".joocli_errors.log"
CONFIG_FILE  = Path.home() / ".joocli_config.json"
MAX_HISTORY  = 500

# ─────────────────────────────────────────────────────────────────────────────
# AI Provider Registry
# ─────────────────────────────────────────────────────────────────────────────
AI_PROVIDERS = {
    "claude": {
        "name":    "Claude (Anthropic)",
        "env_var": "ANTHROPIC_API_KEY",
        "model":   "claude-sonnet-4-20250514",
        "url":     "https://api.anthropic.com/v1/messages",
        "type":    "anthropic",
    },
    "chatgpt": {
        "name":    "ChatGPT (OpenAI)",
        "env_var": "OPENAI_API_KEY",
        "model":   "gpt-4o",
        "url":     "https://api.openai.com/v1/chat/completions",
        "type":    "openai",
    },
    "groq": {
        "name":    "Groq / LLaMA",
        "env_var": "GROQ_API_KEY",
        "model":   "llama-3.3-70b-versatile",
        "url":     "https://api.groq.com/openai/v1/chat/completions",
        "type":    "openai",   # Groq is OpenAI-compatible
    },
    "gemini": {
        "name":    "Google Gemini",
        "env_var": "GEMINI_API_KEY",
        "model":   "gemini-1.5-flash",
        "url":     "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        "type":    "gemini",
    },
}

def _load_config() -> dict:
    """Load persisted config (active provider + saved keys)."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_config(cfg: dict):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass

# Runtime config (loaded once at startup, mutated by :ai set)
_cfg = _load_config()

def _get_api_key(provider_id: str) -> str:
    """Priority: config file (provider-specific) → env var for that provider only."""
    p = AI_PROVIDERS.get(provider_id, {})
    # 1. key saved explicitly for this provider in config
    saved = _cfg.get("keys", {}).get(provider_id, "")
    if saved:
        return saved
    # 2. env var specific to this provider
    return os.environ.get(p.get("env_var", ""), "")

# Known key prefixes per provider — used to warn user of wrong key
_KEY_PREFIXES = {
    "claude":  "sk-ant-",
    "chatgpt": "sk-",
    "groq":    "gsk_",
    "gemini":  "AI",   # Gemini keys usually start with "AIza"
}

def _validate_key(provider_id: str, key: str) -> tuple:
    """Returns (is_valid: bool, warning: str).  Empty key always fails."""
    if not key:
        return False, "no key set"
    prefix = _KEY_PREFIXES.get(provider_id, "")
    if prefix and not key.startswith(prefix):
        others = {pid: pfx for pid, pfx in _KEY_PREFIXES.items()
                  if pid != provider_id and key.startswith(pfx)}
        if others:
            wrong = ", ".join(others.keys())
            return False, f"key looks like a {wrong} key (prefix '{key[:8]}...')"
        # unknown prefix — allow but warn
        return True, f"unusual key prefix '{key[:6]}...'"
    return True, ""

def _active_provider_id() -> str:
    """Return the currently selected provider id (only if its key is valid)."""
    chosen = _cfg.get("active_provider", "")
    if chosen and chosen in AI_PROVIDERS:
        key = _get_api_key(chosen)
        valid, _ = _validate_key(chosen, key)
        if valid:
            return chosen
        # chosen provider has bad/missing key — fall through to auto-pick
    # Auto-pick: first provider with a key that passes prefix validation
    for pid in ["groq", "claude", "chatgpt", "gemini"]:
        key = _get_api_key(pid)
        valid, _ = _validate_key(pid, key)
        if valid:
            return pid
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# Terminal colors / styles
# ─────────────────────────────────────────────────────────────────────────────
R = "\033[0m"
STYLES = {
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "red":     "\033[91m",
    "green":   "\033[92m",
    "yellow":  "\033[93m",
    "blue":    "\033[94m",
    "magenta": "\033[95m",
    "cyan":    "\033[96m",
    "white":   "\033[97m",
    "bg_blue": "\033[44m",
    "bg_dark": "\033[40m",
}

def c(text, *styles):
    prefix = "".join(STYLES.get(s, "") for s in styles)
    return f"{prefix}{text}{R}"

def box(lines, color="cyan", width=58):
    top    = c("╭" + "─" * width + "╮", color)
    bottom = c("╰" + "─" * width + "╯", color)
    mid = []
    for line in lines:
        plain = re.sub(r"\033\[[0-9;]*m", "", line)
        pad = width - 2 - len(plain)
        mid.append(c("│", color) + " " + line + " " * max(pad, 0) + " " + c("│", color))
    return "\n".join([top] + mid + [bottom])

def separator(width=60, color="blue"):
    return c("─" * width, color, "dim")

def header(title, sub="", color="cyan"):
    w = 56
    title_plain = re.sub(r"\033\[[0-9;]*m", "", title)
    pad = (w - len(title_plain)) // 2
    lines = [" " * pad + title]
    if sub:
        sub_plain = re.sub(r"\033\[[0-9;]*m", "", sub)
        pad2 = (w - len(sub_plain)) // 2
        lines.append(c(" " * pad2 + sub, "dim"))
    return box(lines, color, w)

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────
def render_banner():
    logo = [
        c("     ██╗ ██████╗  ██████╗      ██████╗██╗     ██╗", "cyan", "bold"),
        c("     ██║██╔═══██╗██╔═══██╗    ██╔════╝██║     ██║", "cyan", "bold"),
        c("     ██║██║   ██║██║   ██║    ██║     ██║     ██║", "cyan", "bold"),
        c("██   ██║██║   ██║██║   ██║    ██║     ██║     ██║", "blue", "bold"),
        c("╚█████╔╝╚██████╔╝╚██████╔╝    ╚██████╗███████╗██║", "blue", "bold"),
        c(" ╚════╝  ╚═════╝  ╚═════╝      ╚═════╝╚══════╝╚═╝", "dim"),
    ]
    tagline = c("  Smart Terminal Assistant  ·  AI · Docker · Network", "yellow")
    version = c("  v3.0  ·  Multi-provider AI Support", "dim")

    cmds = [
        ("Tab",              "autocomplete commands, flags & paths"),
        (":help CMD",        "explain any command with examples"),
        (":fix ERR",         "instant fix for common errors"),
        (":ai Q",            "ask AI anything"),
        (":ai set PROVIDER", "switch AI (claude/chatgpt/groq/gemini)"),
        (":ai key PROV KEY", "save an API key"),
        (":ai status",       "show configured AI providers"),
        (":docker",          "Docker containers report"),
        (":net",             "network interfaces & open ports"),
        (":ports",           "show all listening ports"),
        (":history N",       "search your shell history"),
        (":last",            "view last captured error"),
        ("exit",             "leave JooCLI"),
    ]
    cmd_lines = []
    for k, v in cmds:
        cmd_lines.append(
            "  " + c(f"{k:<20}", "yellow", "bold") + c(v, "white", "dim")
        )

    parts = ["\n"]
    parts += [l.center(0) for l in logo]
    parts += ["", tagline, version, ""]
    parts.append(c("╭─  Commands " + "─" * 50 + "╮", "blue", "dim"))
    parts += cmd_lines
    parts.append(c("╰" + "─" * 62 + "╯", "blue", "dim"))
    parts.append("")
    return "\n".join(parts)

# ─────────────────────────────────────────────────────────────────────────────
# Command knowledge base
# ─────────────────────────────────────────────────────────────────────────────
COMMAND_DOCS = {
    "ls":   {"desc": "List directory contents",
              "flags": {"-l": "long format", "-a": "show hidden files", "-h": "human-readable sizes",
                        "-R": "recursive", "-t": "sort by time", "-S": "sort by size"},
              "example": "ls -lah /var/log"},
    "cd":   {"desc": "Change working directory",
              "flags": {"-": "go to previous directory"}, "example": "cd ~/projects"},
    "grep": {"desc": "Search text using patterns",
              "flags": {"-i": "ignore case", "-r": "recursive", "-n": "show line numbers",
                        "-v": "invert match", "-l": "list files only", "-c": "count matches",
                        "-E": "extended regex", "-A": "lines after match", "-B": "lines before match"},
              "example": "grep -rn 'TODO' ./src"},
    "find": {"desc": "Search for files",
              "flags": {"-name": "match by name", "-type": "f=file d=dir",
                        "-mtime": "modified N days ago", "-size": "filter by size",
                        "-exec": "run command on results"},
              "example": "find . -name '*.log' -mtime +7 -delete"},
    "curl": {"desc": "Transfer data from/to a server",
              "flags": {"-X": "HTTP method", "-H": "add header", "-d": "POST data",
                        "-o": "output file", "-s": "silent", "-L": "follow redirects", "-v": "verbose"},
              "example": "curl -s -X POST -H 'Content-Type: application/json' -d '{\"k\":\"v\"}' https://api.x.com"},
    "ps":   {"desc": "Snapshot of current processes",
              "flags": {"-aux": "all processes full info", "-ef": "full format",
                        "--sort": "sort e.g. --sort=-%cpu"},
              "example": "ps aux | grep python"},
    "kill": {"desc": "Send signal to a process",
              "flags": {"-9": "SIGKILL (force)", "-15": "SIGTERM (graceful)", "-l": "list signals"},
              "example": "kill -9 $(lsof -t -i:8080)"},
    "tar":  {"desc": "Archive files",
              "flags": {"-c": "create", "-x": "extract", "-v": "verbose",
                        "-f": "filename", "-z": "gzip", "-j": "bzip2"},
              "example": "tar -czvf backup.tar.gz ./mydir"},
    "chmod":{"desc": "Change file permissions",
              "flags": {"-R": "recursive", "+x": "add execute", "755": "rwxr-xr-x", "644": "rw-r--r--"},
              "example": "chmod +x script.sh"},
    "ssh":  {"desc": "Secure remote login",
              "flags": {"-i": "identity key", "-p": "port", "-L": "local forward",
                        "-R": "remote forward", "-N": "no command", "-v": "verbose"},
              "example": "ssh -i ~/.ssh/id_rsa user@host -p 2222"},
    "git":  {"desc": "Distributed version control",
              "flags": {"status": "show working tree", "add": "stage changes", "commit": "record",
                        "push": "upload", "pull": "fetch+merge", "log": "show commits",
                        "diff": "show changes", "stash": "stash", "rebase": "reapply",
                        "cherry-pick": "apply specific commit"},
              "example": "git log --oneline --graph --decorate"},
    "docker":{"desc": "Container management",
               "flags": {"ps": "list containers", "images": "list images", "run": "run container",
                         "stop": "stop", "rm": "remove container", "rmi": "remove image",
                         "logs": "view logs", "exec": "run in container", "build": "build image",
                         "inspect": "inspect details", "stats": "live resource usage"},
               "example": "docker run -d -p 8080:80 --name myapp nginx"},
    "awk":  {"desc": "Pattern scanning & text processing",
              "flags": {"-F": "field separator", "NR": "row number", "NF": "num fields",
                        "$1": "first field", "BEGIN": "before", "END": "after"},
              "example": "awk -F: '{print $1}' /etc/passwd"},
    "sed":  {"desc": "Stream editor",
              "flags": {"-i": "in-place edit", "-n": "suppress output", "-e": "add script",
                        "s/old/new/g": "substitute all", "d": "delete line"},
              "example": "sed -i 's/localhost/0.0.0.0/g' config.yaml"},
    "df":   {"desc": "Disk space usage",
              "flags": {"-h": "human-readable", "-T": "filesystem type", "-i": "inodes"},
              "example": "df -h /"},
    "du":   {"desc": "Directory space usage",
              "flags": {"-h": "human-readable", "-s": "summarize", "-d": "max depth",
                        "--exclude": "exclude pattern"},
              "example": "du -sh * | sort -hr | head -20"},
    "netstat":{"desc": "Network statistics",
                "flags": {"-t": "TCP", "-u": "UDP", "-l": "listening",
                           "-n": "numeric", "-p": "show process"},
                "example": "netstat -tlnp"},
    "lsof": {"desc": "List open files / connections",
              "flags": {"-i": "network", "-t": "PIDs only", "-p": "by PID", "-u": "by user"},
              "example": "lsof -i :8080"},
    "top":  {"desc": "Live system processes",
              "flags": {"-b": "batch", "-n": "iterations", "-u": "filter user", "-d": "delay"},
              "example": "top -b -n 1 | head -20"},
    "cat":  {"desc": "Display file contents",
              "flags": {"-n": "number lines", "-A": "show special chars"}, "example": "cat -n file.txt"},
    "head": {"desc": "Output first lines",
              "flags": {"-n": "number of lines"}, "example": "head -n 50 app.log"},
    "tail": {"desc": "Output last lines",
              "flags": {"-n": "number of lines", "-f": "follow"}, "example": "tail -f /var/log/syslog"},
    "wc":   {"desc": "Count lines/words/chars",
              "flags": {"-l": "lines", "-w": "words", "-c": "bytes"}, "example": "wc -l *.py"},
    "sort": {"desc": "Sort lines",
              "flags": {"-r": "reverse", "-n": "numeric", "-k": "column", "-u": "unique"},
              "example": "sort -t',' -k2 -n data.csv"},
    "uniq": {"desc": "Remove/count duplicate lines",
              "flags": {"-c": "count", "-d": "only dupes", "-u": "only unique"},
              "example": "sort access.log | uniq -c | sort -rn | head"},
    "xargs":{"desc": "Build commands from stdin",
              "flags": {"-I{}": "placeholder", "-P": "parallel jobs", "-n": "max args"},
              "example": "find . -name '*.tmp' | xargs rm -f"},
    "rsync":{"desc": "Remote file sync",
              "flags": {"-a": "archive", "-v": "verbose", "-z": "compress",
                        "--delete": "delete removed", "--exclude": "exclude", "--dry-run": "simulate"},
              "example": "rsync -avz --delete ./src/ user@host:/dest/"},
    "systemctl":{"desc": "Systemd service manager",
                  "flags": {"start": "start", "stop": "stop", "restart": "restart",
                             "status": "status", "enable": "enable at boot", "disable": "disable"},
                  "example": "systemctl status nginx"},
    "journalctl":{"desc": "Query systemd journal",
                   "flags": {"-u": "by service", "-f": "follow", "-n": "last N lines",
                              "--since": "since time", "-p": "priority"},
                   "example": "journalctl -u nginx -n 100 --since '1 hour ago'"},
    "ping": {"desc": "Test host connectivity",
              "flags": {"-c": "count", "-i": "interval", "-t": "TTL"}, "example": "ping -c 4 google.com"},
    "nmap": {"desc": "Network scanner",
              "flags": {"-sV": "detect versions", "-p": "port range", "-A": "aggressive", "--open": "open ports"},
              "example": "nmap -sV -p 1-1000 192.168.1.0/24"},
    "env":  {"desc": "Show/set environment variables",
              "flags": {"-i": "empty environment"}, "example": "env | grep PATH"},
}

# ─────────────────────────────────────────────────────────────────────────────
# Error patterns
# ─────────────────────────────────────────────────────────────────────────────
ERROR_PATTERNS = [
    (r"command not found",
     "Command missing or not in PATH.\nFix: Check spelling · install the package · add to $PATH"),
    (r"permission denied",
     "Insufficient permissions.\nFix: prefix with 'sudo' · check 'ls -la' · fix with 'chmod'"),
    (r"no such file or directory",
     "File or path doesn't exist.\nFix: Check path with 'ls' · use Tab completion · create the file"),
    (r"connection refused",
     "Nothing listening on that port.\nFix: 'systemctl status <svc>' · check ports with 'netstat -tlnp'"),
    (r"address already in use",
     "Port already taken.\nFix: 'lsof -i :<PORT>' to find PID · 'kill -9 <PID>' to free it"),
    (r"disk quota exceeded|no space left on device",
     "Disk is full.\nFix: 'df -h' to check · 'du -sh * | sort -hr' to find large files"),
    (r"broken pipe",
     "Downstream process exited early.\nFix: Usually harmless in pipelines. Check the receiving command."),
    (r"too many open files",
     "File descriptor limit hit.\nFix: 'ulimit -n 65536' to raise limit · check for fd leaks"),
    (r"segmentation fault|segfault",
     "Program accessed invalid memory.\nFix: Run under 'gdb' · check for null pointers / buffer overflows"),
    (r"cannot allocate memory|out of memory",
     "RAM exhausted.\nFix: 'free -h' · kill hogs with 'top' · add swap space"),
    (r"read-only file system",
     "Filesystem mounted read-only.\nFix: 'mount -o remount,rw /' · check /etc/fstab"),
    (r"syntax error",
     "Shell script syntax error.\nFix: 'bash -n script.sh' to validate · check quotes & brackets"),
    (r"operation not permitted",
     "Kernel-level restriction.\nFix: Check AppArmor/SELinux · capabilities · container constraints"),
    (r"network is unreachable",
     "No route to destination.\nFix: 'ip addr' · 'ip route' · 'cat /etc/resolv.conf'"),
    (r"ssl.*certificate|certificate verify failed",
     "TLS certificate error.\nFix: Check system clock · 'update-ca-certificates' · '-k' flag (dev only)"),
    (r"\\r|\\r.*no such file|python3\\r",
     "Windows CRLF line endings (\\r\\n) in script.\nFix: Run: sed -i 's/\\r//' yourfile.py  OR  dos2unix yourfile.py"),
]

# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────
def load_shell_history():
    history = []
    for hf in ["~/.bash_history", "~/.zsh_history"]:
        p = Path(hf).expanduser()
        if p.exists():
            try:
                for line in p.read_text(errors="ignore").splitlines():
                    m = re.match(r"^: \d+:\d+;(.+)", line)
                    history.append(m.group(1) if m else line)
            except Exception:
                pass
    return [h for h in history if h.strip()]

def log_error(command, err):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] CMD: {command}\nERR: {err}\n{'─'*60}\n")

def match_error(text):
    for pat, advice in ERROR_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return advice
    return None

def run_cmd(cmd_str, timeout=15):
    """Run a shell command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -1
    except Exception as e:
        return "", str(e), -1

# ─────────────────────────────────────────────────────────────────────────────
# Multi-provider AI  ──  the heart of the new feature
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = "You are a concise, practical Linux/DevOps CLI assistant. Use plain text. Be direct."

# Browser-like User-Agent avoids Cloudflare 403/1010 blocks (common with urllib default UA)
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def _call_anthropic(provider: dict, api_key: str, prompt: str) -> str:
    payload = json.dumps({
        "model": provider["model"],
        "max_tokens": 700,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        provider["url"],
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read())
        return data["content"][0]["text"]

def _call_openai_compat(provider: dict, api_key: str, prompt: str) -> str:
    """Works for OpenAI, Groq (and any OpenAI-compatible endpoint)."""
    payload = json.dumps({
        "model": provider["model"],
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    }).encode()
    req = urllib.request.Request(
        provider["url"],
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

def _call_gemini(provider: dict, api_key: str, prompt: str) -> str:
    url = f"{provider['url']}?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": f"{_SYSTEM_PROMPT}\n\n{prompt}"}]}]
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"]

def ask_ai(prompt: str) -> str:
    """Call the active AI provider. Falls back gracefully with a helpful message."""
    pid = _active_provider_id()
    if not pid:
        lines = [
            c("  No AI provider configured.", "yellow"),
            c("  Set one of these environment variables:", "dim"),
        ]
        for p in AI_PROVIDERS.values():
            lines.append(f"    export {p['env_var']}=your_key_here")
        lines.append(c("  Or use: :ai key <provider> <your_key>", "dim"))
        return "\n".join(lines)

    provider = AI_PROVIDERS[pid]
    api_key  = _get_api_key(pid)

    try:
        if provider["type"] == "anthropic":
            return _call_anthropic(provider, api_key, prompt)
        elif provider["type"] == "openai":
            return _call_openai_compat(provider, api_key, prompt)
        elif provider["type"] == "gemini":
            return _call_gemini(provider, api_key, prompt)
        else:
            return c(f"  Unknown provider type: {provider['type']}", "red")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        if e.code == 403 and ("1010" in body or "error code" in body.lower()):
            msg = [
                c("  Cloudflare blocked the request (error 403/1010).", "red"),
                c("  Common on WSL / VPS IPs. Solutions:", "yellow"),
                c("    1. Use a VPN or switch to a residential network", "dim"),
                c("    2. Try another provider:  :ai set claude  or  :ai set chatgpt", "dim"),
                c("    3. Run from a regular Windows terminal (not WSL)", "dim"),
            ]
            return "\n".join(msg)
        return c(f"  API error {e.code}: {body}", "red")
    except Exception as e:
        return c(f"  Connection error: {e}", "red")

def ai_status() -> str:
    """Show which providers are configured and which is active."""
    active = _active_provider_id()
    lines  = [c("  AI PROVIDERS", "yellow", "bold"), separator()]
    for pid, p in AI_PROVIDERS.items():
        key      = _get_api_key(pid)
        valid, warn = _validate_key(pid, key)
        masked   = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else ("set" if key else "—")
        is_active = (pid == active)

        if is_active:
            status = c("✓  active ", "green")
        elif valid:
            status = c("✓  ready  ", "cyan")
        elif key and not valid:
            status = c("⚠  bad key", "yellow")
        else:
            status = c("✗  no key ", "red")

        indicator = c("►", "yellow", "bold") if is_active else " "
        line = f"  {indicator} {c(pid, 'cyan'):<14} {status}  key={c(masked, 'dim')}  ({p['name']})"
        lines.append(line)
        if warn and key:
            lines.append(c(f"      ⚠  {warn}", "yellow"))

    lines.append("")
    lines.append(c("  Expected key prefixes:", "dim"))
    for pid, pfx in _KEY_PREFIXES.items():
        lines.append(c(f"    {pid:<10} starts with  {pfx}...", "dim"))
    lines.append("")
    lines.append(c("  Commands:", "dim"))
    lines.append(c("    :ai set <provider>       – switch active provider", "dim"))
    lines.append(c("    :ai key <provider> <key> – save a key (stored in ~/.joocli_config.json)", "dim"))
    return "\n".join(lines)

def ai_set_provider(pid: str) -> str:
    pid = pid.lower().strip()
    if pid not in AI_PROVIDERS:
        valid = ", ".join(AI_PROVIDERS.keys())
        return c(f"  Unknown provider '{pid}'. Valid: {valid}", "red")
    _cfg["active_provider"] = pid
    _save_config(_cfg)
    p   = AI_PROVIDERS[pid]
    key = _get_api_key(pid)
    valid, warn = _validate_key(pid, key)
    if not key:
        return (c(f"  Switched to {p['name']}.\n", "green") +
                c(f"  ⚠  No key found. Set it with:\n", "yellow") +
                c(f"     :ai key {pid} YOUR_KEY\n  or export {p['env_var']}=YOUR_KEY", "dim"))
    if not valid:
        return (c(f"  Switched to {p['name']}.\n", "green") +
                c(f"  ⚠  Warning: {warn}\n", "yellow") +
                c(f"     Use: :ai key {pid} YOUR_{pid.upper()}_KEY", "dim"))
    return c(f"  Switched to {p['name']} ✓", "green")

def ai_save_key(pid: str, key: str) -> str:
    pid = pid.lower().strip()
    if pid not in AI_PROVIDERS:
        valid = ", ".join(AI_PROVIDERS.keys())
        return c(f"  Unknown provider '{pid}'. Valid: {valid}", "red")
    key = key.strip()
    valid, warn = _validate_key(pid, key)
    if not valid:
        return (c(f"  ⚠  Key rejected: {warn}\n", "yellow") +
                c(f"     Expected prefix for {pid}: '{_KEY_PREFIXES.get(pid, '?')}...'\n", "dim") +
                c(f"     If you are sure this is correct, use the env var instead:", "dim") + "\n" +
                c(f"     export {AI_PROVIDERS[pid]['env_var']}=your_key", "dim"))
    if "keys" not in _cfg:
        _cfg["keys"] = {}
    _cfg["keys"][pid] = key
    _save_config(_cfg)
    msg = c(f"  Key for '{pid}' saved ✓", "green")
    if warn:
        msg += "\n" + c(f"  Note: {warn}", "yellow")
    return msg
# ─────────────────────────────────────────────────────────────────────────────
# Docker Inspector
# ─────────────────────────────────────────────────────────────────────────────
def docker_report():
    out, err, code = run_cmd("docker info --format '{{.ServerVersion}}' 2>/dev/null")
    if code != 0:
        return c("  Docker is not running or not installed.", "red")

    lines = []
    lines.append(c(f"  Docker Engine  v{out}", "cyan", "bold"))
    lines.append(separator())

    lines.append(c("  CONTAINERS", "yellow", "bold"))
    stdout, _, _ = run_cmd(
        "docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}|{{.Ports}}|{{.ID}}'"
    )
    if stdout:
        lines.append(f"  {'NAME':<22} {'STATUS':<22} {'IMAGE':<22} {'PORTS':<28} {'ID':<12}")
        lines.append(c("  " + "─" * 108, "dim"))
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 5:
                continue
            name, status, image, ports, cid = parts[0], parts[1], parts[2], parts[3], parts[4]
            if "Up" in status:
                status_str = c(f"{status:<22}", "green")
            elif "Exited" in status:
                status_str = c(f"{status:<22}", "red")
            else:
                status_str = c(f"{status:<22}", "yellow")
            lines.append(
                f"  {c(name, 'bold'):<30} {status_str} {image:<22} {c(ports or '—', 'cyan'):<28} {c(cid[:12], 'dim')}"
            )
    else:
        lines.append(c("  No containers found.", "dim"))

    lines.append("")
    lines.append(separator())

    lines.append(c("  IMAGES", "yellow", "bold"))
    stdout, _, _ = run_cmd(
        "docker images --format '{{.Repository}}:{{.Tag}}|{{.Size}}|{{.ID}}|{{.CreatedSince}}'"
    )
    if stdout:
        lines.append(f"  {'IMAGE':<38} {'SIZE':<12} {'ID':<14} {'CREATED'}")
        lines.append(c("  " + "─" * 80, "dim"))
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 4:
                continue
            img, size, iid, created = parts[0], parts[1], parts[2], parts[3]
            lines.append(
                f"  {c(img, 'cyan'):<46} {size:<12} {c(iid[:12], 'dim'):<14} {c(created, 'dim')}"
            )
    else:
        lines.append(c("  No images found.", "dim"))

    lines.append("")
    lines.append(separator())

    lines.append(c("  DOCKER NETWORKS", "yellow", "bold"))
    stdout, _, _ = run_cmd("docker network ls --format '{{.Name}}|{{.Driver}}|{{.Scope}}'")
    if stdout:
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 3:
                continue
            lines.append(f"  {c(parts[0], 'white'):<22} driver={c(parts[1], 'cyan')}  scope={c(parts[2], 'dim')}")
    else:
        lines.append(c("  No networks.", "dim"))

    lines.append("")
    lines.append(separator())

    lines.append(c("  VOLUMES", "yellow", "bold"))
    stdout, _, _ = run_cmd("docker volume ls --format '{{.Name}}|{{.Driver}}'")
    if stdout:
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 2:
                continue
            lines.append(f"  {c(parts[0], 'white'):<38} driver={c(parts[1], 'cyan')}")
    else:
        lines.append(c("  No volumes.", "dim"))

    lines.append("")
    lines.append(c("  Tip: ':docker logs <name>' · ':docker exec <name>' · ':ai fix my docker issue'", "dim"))
    return "\n".join(lines)

def docker_logs(name, tail=50):
    out, err, code = run_cmd(f"docker logs --tail {tail} {name} 2>&1")
    if code != 0:
        return c(f"  Error: {err}", "red")
    return c(f"  ── Logs: {name} (last {tail} lines) ──\n", "yellow") + (out or c("  (no output)", "dim"))

def docker_exec(name, cmd_str="sh"):
    print(c(f"\n  Entering container '{name}' (type 'exit' to leave)\n", "cyan"))
    os.system(f"docker exec -it {name} {cmd_str}")

def docker_inspect(name):
    out, err, code = run_cmd(f"docker inspect {name}")
    if code != 0:
        return c(f"  Error: {err}", "red")
    try:
        data = json.loads(out)
        if not data:
            return c("  No data.", "dim")
        d = data[0]
        cfg  = d.get("Config", {})
        net  = d.get("NetworkSettings", {})
        host = d.get("HostConfig", {})
        lines = [
            c(f"  ── Inspect: {name} ──", "yellow", "bold"), "",
            f"  {'ID':<18} {c(d.get('Id','')[:20], 'dim')}",
            f"  {'Image':<18} {c(cfg.get('Image',''), 'cyan')}",
            f"  {'Status':<18} {c(d.get('State',{}).get('Status',''), 'green')}",
            f"  {'Started':<18} {d.get('State',{}).get('StartedAt','')[:19]}",
            f"  {'Restart policy':<18} {host.get('RestartPolicy',{}).get('Name','')}",
            f"  {'Working dir':<18} {cfg.get('WorkingDir','/')}",
            "",
            c("  ENV VARS", "yellow"),
        ]
        for env in (cfg.get("Env") or [])[:10]:
            lines.append(f"  {c('·', 'dim')} {env}")
        lines += ["", c("  PORT BINDINGS", "yellow")]
        for p, v in (net.get("Ports") or {}).items():
            if v:
                for b in v:
                    lines.append(f"  {c(p, 'cyan')} → {b.get('HostIp','0.0.0.0')}:{c(b.get('HostPort','?'), 'green')}")
            else:
                lines.append(f"  {c(p, 'dim')} (not published)")
        lines += ["", c("  MOUNTS", "yellow")]
        for m in (d.get("Mounts") or [])[:8]:
            lines.append(f"  {c(m.get('Source','?'), 'dim')} → {c(m.get('Destination','?'), 'cyan')}")
        return "\n".join(lines)
    except Exception as e:
        return c(f"  Parse error: {e}", "red")

# ─────────────────────────────────────────────────────────────────────────────
# Network Inspector
# ─────────────────────────────────────────────────────────────────────────────
def net_report():
    lines = []
    lines.append(c("  NETWORK INTERFACES", "yellow", "bold"))
    lines.append(separator())

    out, _, code = run_cmd("ip addr show 2>/dev/null")
    if code != 0:
        out, _, _ = run_cmd("ifconfig 2>/dev/null")

    if out:
        for line in out.splitlines():
            m = re.match(r"^\d+:\s+(\S+):", line)
            if m:
                lines.append(f"\n  {c(m.group(1), 'cyan', 'bold')}")
            ipv4 = re.search(r"inet (\d+\.\d+\.\d+\.\d+)(?:/(\d+))?", line)
            if ipv4:
                ip  = ipv4.group(1)
                pfx = f"/{ipv4.group(2)}" if ipv4.group(2) else ""
                lines.append(f"    {c('IPv4', 'dim'):<14} {c(ip + pfx, 'green')}")
            ipv6 = re.search(r"inet6 ([0-9a-f:]+)(?:/(\d+))?", line)
            if ipv6 and "fe80" not in ipv6.group(1):
                lines.append(f"    {c('IPv6', 'dim'):<14} {c(ipv6.group(1), 'blue')}")
            mac = re.search(r"ether ([0-9a-f:]{17})", line)
            if mac:
                lines.append(f"    {c('MAC', 'dim'):<14} {c(mac.group(1), 'dim')}")
    else:
        lines.append(c("  Could not retrieve interfaces.", "red"))

    lines.append(f"\n{separator()}")
    lines.append(c("  ROUTING", "yellow", "bold"))
    out, _, _ = run_cmd("ip route 2>/dev/null || netstat -rn 2>/dev/null | head -8")
    if out:
        for line in out.splitlines()[:6]:
            lines.append(f"  {c(line, 'dim')}")

    lines.append(f"\n{separator()}")
    lines.append(c("  DNS SERVERS", "yellow", "bold"))
    out, _, _ = run_cmd("cat /etc/resolv.conf 2>/dev/null | grep ^nameserver")
    if out:
        for line in out.splitlines():
            ip = line.split()[-1] if line.split() else ""
            lines.append(f"  {c('nameserver', 'dim'):<16} {c(ip, 'green')}")
    else:
        lines.append(c("  /etc/resolv.conf not readable.", "dim"))

    return "\n".join(lines)

def ports_report():
    lines = [c("  LISTENING PORTS", "yellow", "bold"), separator()]

    out, _, code = run_cmd("ss -tlnp 2>/dev/null")
    if code != 0 or not out:
        out, _, _ = run_cmd("netstat -tlnp 2>/dev/null")

    if out:
        lines.append(f"  {'PROTO':<8} {'LOCAL ADDRESS':<26} {'PROCESS'}")
        lines.append(c("  " + "─" * 60, "dim"))
        for line in out.splitlines()[1:]:
            parts = line.split()
            if not parts:
                continue
            proto = parts[0] if parts else ""
            addr  = parts[3] if len(parts) > 3 else parts[-1]
            proc  = parts[-1] if "users:" in line or "pid" in line.lower() else "—"
            port_match = re.search(r":(\d+)$", addr)
            port_str = c(addr, "green") if port_match else c(addr, "dim")
            lines.append(f"  {c(proto, 'cyan'):<16} {port_str:<34} {c(proc, 'dim')}")
    else:
        lines.append(c("  Could not retrieve ports (try running as root).", "yellow"))

    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Completer
# ─────────────────────────────────────────────────────────────────────────────
class JooCompleter:
    JOO_CMDS = [
        ":help", ":fix", ":ai", ":ai set", ":ai key", ":ai status",
        ":docker", ":docker logs", ":docker exec", ":docker inspect",
        ":docker stop", ":docker start", ":docker restart", ":docker rm",
        ":net", ":ports", ":history", ":last", ":clear", "exit", "quit",
    ]

    def __init__(self):
        self.commands = sorted(COMMAND_DOCS.keys())
        for p in os.environ.get("PATH", "").split(":"):
            try:
                for f in Path(p).iterdir():
                    if f.is_file() and os.access(f, os.X_OK):
                        self.commands.append(f.name)
            except Exception:
                pass
        self.commands = sorted(set(self.commands))

    def complete(self, text, state):
        try:
            line = readline.get_line_buffer()
            tokens = line.split()

            if text.startswith(":"):
                matches = [cmd for cmd in self.JOO_CMDS if cmd.startswith(text)]
                return matches[state] if state < len(matches) else None

            if not tokens or (len(tokens) == 1 and not line.endswith(" ")):
                matches = [cmd for cmd in self.commands if cmd.startswith(text)]
            elif tokens and tokens[0] in COMMAND_DOCS and text.startswith("-"):
                flags = list(COMMAND_DOCS[tokens[0]]["flags"].keys())
                matches = [f for f in flags if f.startswith(text)]
            else:
                expanded = os.path.expanduser(text) if text else "."
                base   = os.path.dirname(expanded) or "."
                prefix = os.path.basename(expanded)
                try:
                    entries = os.listdir(base)
                except OSError:
                    entries = []
                raw = [os.path.join(base, e) if base != "." else e
                       for e in entries if e.startswith(prefix)]
                matches = [r + ("/" if os.path.isdir(r) else " ") for r in raw]

            return matches[state] if state < len(matches) else None
        except Exception:
            return None

# ─────────────────────────────────────────────────────────────────────────────
# Main REPL
# ─────────────────────────────────────────────────────────────────────────────
class JooCLI:
    PROMPT = c("joo", "cyan", "bold") + c(" ❯ ", "blue")

    def __init__(self):
        self._completer = JooCompleter()
        self._setup_readline()
        self.shell_history = load_shell_history()
        self.last_error    = ""
        print(render_banner())
        # Show active AI provider on startup
        pid = _active_provider_id()
        if pid:
            print(c(f"  AI: {AI_PROVIDERS[pid]['name']} active  (use ':ai status' for details)\n", "dim"))
        else:
            print(c("  AI: no provider configured  (use ':ai key <provider> <key>' to add one)\n", "yellow"))

    def _setup_readline(self):
        readline.set_completer(self._completer.complete)
        readline.parse_and_bind("tab: complete")
        readline.set_completer_delims(" \t\n;|&<>")
        if HISTORY_FILE.exists():
            try:
                readline.read_history_file(str(HISTORY_FILE))
            except Exception:
                pass
        readline.set_history_length(MAX_HISTORY)

    def _save_history(self):
        try:
            readline.write_history_file(str(HISTORY_FILE))
        except Exception:
            pass

    def dispatch(self, line):
        line  = line.strip()
        if not line:
            return False

        parts = line.split(None, 1)
        token = parts[0].lower()
        arg   = parts[1].strip() if len(parts) > 1 else ""

        if token == ":help":
            self._cmd_help(arg)
        elif token == ":fix":
            self._cmd_fix(arg)
        elif token == ":ai":
            self._cmd_ai(arg)
        elif token == ":docker":
            self._cmd_docker(arg)
        elif token == ":net":
            print(f"\n{net_report()}\n")
        elif token == ":ports":
            print(f"\n{ports_report()}\n")
        elif token == ":history":
            self._cmd_history(arg)
        elif token == ":last":
            self._cmd_last()
        elif token == ":clear":
            os.system("clear")
        elif token == ":run":
            self._cmd_run(arg)
        elif token.startswith(":"):
            print(c(f"\n  Unknown command '{token}'.\n"
                    f"  Try: :help :fix :ai :docker :net :ports :history :last :clear\n", "yellow"))
        elif token in ("exit", "quit", "q"):
            self._save_history()
            print(c("\n  Goodbye from JooCLI!\n", "cyan"))
            return True
        elif token == "help":
            print(render_banner())
        else:
            self._cmd_run(line)

        return False

    def run(self):
        while True:
            try:
                line = input(self.PROMPT)
            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                self._save_history()
                print(c("\n  Goodbye from JooCLI!\n", "cyan"))
                break
            if self.dispatch(line):
                break

    # ── handlers ─────────────────────────────────────────────────────

    def _cmd_help(self, arg):
        name = arg.strip().lower()
        if not name:
            print(c("  Usage: :help COMMAND  (e.g. :help grep)", "yellow"))
            return
        if name in COMMAND_DOCS:
            doc = COMMAND_DOCS[name]
            print(f"\n  {c(name, 'cyan', 'bold')}  —  {doc['desc']}\n")
            print(c("  FLAGS", "yellow"))
            for flag, desc in doc["flags"].items():
                print(f"  {c(flag, 'green'):<28} {c(desc, 'dim')}")
            print(f"\n  {c('EXAMPLE', 'yellow')}  {doc['example']}\n")
        else:
            out, _, _ = run_cmd(f"man -f {name} 2>/dev/null")
            if out:
                print(c(f"\n  {out}\n", "cyan"))
            else:
                print(c(f"  No docs for '{name}'. Try ':ai what does {name} do?'", "yellow"))

    def _cmd_fix(self, arg):
        text = arg.strip() or self.last_error
        if not text:
            print(c("  Usage: :fix 'error text'   or just ':fix' to reuse last error", "yellow"))
            return
        advice = match_error(text)
        if advice:
            print(f"\n  {c('Fix suggestion', 'green', 'bold')}")
            for line in advice.splitlines():
                print(f"  {c(line, 'white')}")
            print()
        else:
            print(c(f"  No pattern matched. Try ':ai fix: {text}'", "yellow"))

    def _cmd_ai(self, arg):
        """
        Sub-commands:
            :ai status            – show all providers
            :ai set <provider>    – switch active provider
            :ai key <prov> <key>  – save a key
            :ai <question>        – ask a question
        """
        if not arg.strip():
            print(c("  Usage: :ai <question>  |  :ai status  |  :ai set <provider>  |  :ai key <provider> <key>", "yellow"))
            return

        parts = arg.split(None, 2)
        sub   = parts[0].lower()

        if sub == "status":
            print(f"\n{ai_status()}\n")
            return

        if sub == "set":
            pid = parts[1].lower() if len(parts) > 1 else ""
            if not pid:
                valid = ", ".join(AI_PROVIDERS.keys())
                print(c(f"  Usage: :ai set <provider>   valid: {valid}", "yellow"))
                return
            print(f"\n  {ai_set_provider(pid)}\n")
            return

        if sub == "key":
            if len(parts) < 3:
                valid = ", ".join(AI_PROVIDERS.keys())
                print(c(f"  Usage: :ai key <provider> <api_key>   providers: {valid}", "yellow"))
                return
            pid = parts[1].lower()
            key = parts[2]
            print(f"\n  {ai_save_key(pid, key)}\n")
            return

        # Default: ask the AI
        pid = _active_provider_id()
        provider_name = AI_PROVIDERS[pid]["name"] if pid else "AI"
        print(c(f"\n  Asking {provider_name}...\n", "cyan"))
        ctx = f"Linux/macOS terminal user. Question: {arg}"
        if self.last_error:
            ctx += f"\n\nLast error:\n{self.last_error}"
        answer = ask_ai(ctx)
        print()
        for line in answer.splitlines():
            print(f"  {line}")
        print()

    def _cmd_docker(self, arg):
        parts = arg.strip().split(None, 1)
        sub   = parts[0].lower() if parts else ""
        rest  = parts[1].strip() if len(parts) > 1 else ""

        if sub == "logs":
            tokens = rest.split()
            name = tokens[0] if tokens else ""
            tail = int(tokens[1]) if len(tokens) > 1 else 50
            if not name:
                print(c("  Usage: :docker logs <container> [lines]", "yellow")); return
            print(f"\n{docker_logs(name, tail)}\n")
        elif sub == "exec":
            tokens = rest.split()
            name = tokens[0] if tokens else ""
            sh   = tokens[1] if len(tokens) > 1 else "sh"
            if not name:
                print(c("  Usage: :docker exec <container> [sh|bash]", "yellow")); return
            docker_exec(name, sh)
        elif sub == "inspect":
            if not rest:
                print(c("  Usage: :docker inspect <container>", "yellow")); return
            print(f"\n{docker_inspect(rest)}\n")
        elif sub in ("stop", "start", "restart", "rm"):
            if not rest:
                print(c(f"  Usage: :docker {sub} <container>", "yellow")); return
            out, err, code = run_cmd(f"docker {sub} {rest}")
            if code == 0:
                print(c(f"\n  ✓  docker {sub} {rest}\n", "green"))
            else:
                print(c(f"\n  ✗  {err}\n", "red"))
        else:
            print(f"\n{docker_report()}\n")

    def _cmd_history(self, arg):
        parts = arg.split(None, 1)
        try:
            limit  = int(parts[0]) if parts else 20
            search = parts[1] if len(parts) > 1 else ""
        except ValueError:
            limit, search = 20, parts[0] if parts else ""
        hist = self.shell_history
        if search:
            hist = [h for h in hist if search.lower() in h.lower()]
        hist = hist[-limit:]
        suffix = f" matching '{search}'" if search else ""
        print(f"\n  {c(f'Last {len(hist)} commands{suffix}', 'cyan')}\n")
        for i, h in enumerate(hist, 1):
            print(f"  {c(str(i).rjust(3), 'yellow')}  {h}")
        print()

    def _cmd_last(self):
        if self.last_error:
            print(f"\n  {c('Last error:', 'red', 'bold')}\n  {self.last_error}\n")
        elif LOG_FILE.exists():
            lines = LOG_FILE.read_text().strip().splitlines()
            print(c("\n  Error log (last 20 lines):\n", "yellow"))
            for line in lines[-20:]:
                print(f"  {line}")
            print()
        else:
            print(c("  No errors captured yet.", "green"))

    def _cmd_run(self, arg):
        if not arg.strip():
            return
        print()
        out, err, code = run_cmd(arg, timeout=30)
        if out:
            print(out)
        if code != 0 and err:
            self.last_error = err
            log_error(arg, err)
            print(c(f"\n  [exit {code}]  {err}", "red"))
            advice = match_error(err)
            if advice:
                print(c("\n  Quick fix:", "yellow", "bold"))
                for line in advice.splitlines():
                    print(f"  {line}")
            else:
                print(c("  Tip: ':ai fix the error above' for AI help.", "dim"))
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    # Auto-fix Windows CRLF on the script itself (WSL safety)
    try:
        this = Path(__file__).read_bytes()
        if b"\r\n" in this:
            Path(__file__).write_bytes(this.replace(b"\r\n", b"\n"))
    except Exception:
        pass

    cli = JooCLI()
    if len(sys.argv) > 1:
        cli.dispatch(" ".join(sys.argv[1:]))
    else:
        cli.run()

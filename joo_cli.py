#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JooCLI — Smart Terminal Assistant  v4.1
Autocomplete · AI Troubleshooting · Docker Inspector · Network Tools

Usage:
    python3 joo_cli.py

Requires:
    - Python 3.8+  (stdlib only — no pip needed)
    - One or more AI API keys (optional, for AI features):
        ANTHROPIC_API_KEY  → Claude (claude-sonnet-4-20250514)
        OPENAI_API_KEY     → ChatGPT (gpt-4o)
        GROQ_API_KEY       → Groq / LLaMA (llama-3.3-70b-versatile)
        GEMINI_API_KEY     → Google Gemini (gemini-2.0-flash)

What's new in v4.1:
    ✓ 12-mode context-aware Tab completer
       - :docker logs/exec/stop/start/rm → live container names
       - :ai set/key → provider names
       - :net scan/check/dns → sub-command list
       - git/systemctl → sub-commands
       - ssh/scp → ~/.ssh/config + known_hosts hosts
       - :ping/:trace/:dns → recent hosts from history
       - flags (-) → per-command flag list
       - fuzzy match on typos (≥3 chars)
       - double-Tab shows formatted menu
    ✓ Fuzzy container name suggestions on typos
       (':docker logs mongo-oreder' → Did you mean: mongo-order?)
    ✓ Live Docker name cache (refreshes every 8s)
    ✓ Ctrl-C no longer crashes the shell
    ✓ Streaming AI for all 4 providers
"""

import os
import re
import sys
import json
import time
import readline
import subprocess
import urllib.request
import urllib.error
import socket
import http.client
import ssl
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
# Terminal colors / styles
# ─────────────────────────────────────────────────────────────────────────────
R = "\033[0m"
STYLES = {
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "italic":  "\033[3m",
    "red":     "\033[91m",
    "green":   "\033[92m",
    "yellow":  "\033[93m",
    "blue":    "\033[94m",
    "magenta": "\033[95m",
    "cyan":    "\033[96m",
    "white":   "\033[97m",
    "bg_blue": "\033[44m",
    "bg_dark": "\033[40m",
    "bg_red":  "\033[41m",
    "bg_green":"\033[42m",
}

def c(text, *styles):
    prefix = "".join(STYLES.get(s, "") for s in styles)
    return f"{prefix}{text}{R}"

def strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)

def box(lines, color="cyan", width=58):
    top    = c("╭" + "─" * width + "╮", color)
    bottom = c("╰" + "─" * width + "╯", color)
    mid = []
    for line in lines:
        plain = strip_ansi(line)
        pad = width - 2 - len(plain)
        mid.append(c("│", color) + " " + line + " " * max(pad, 0) + " " + c("│", color))
    return "\n".join([top] + mid + [bottom])

def separator(width=60, color="blue"):
    return c("─" * width, color, "dim")

def section_header(title, color="yellow"):
    return f"\n  {c('▸ ' + title, color, 'bold')}\n  {c('─' * (len(title) + 4), color, 'dim')}"

# ─────────────────────────────────────────────────────────────────────────────
# AI Provider Registry
# ─────────────────────────────────────────────────────────────────────────────
AI_PROVIDERS = {
    "claude": {
        "name":    "Claude (Anthropic)",
        "env_var": "ANTHROPIC_API_KEY",
        "model":   "claude-sonnet-4-20250514",
        "url":     "https://api.anthropic.com/v1/messages",
        "stream_url": "https://api.anthropic.com/v1/messages",
        "type":    "anthropic",
    },
    "chatgpt": {
        "name":    "ChatGPT (OpenAI)",
        "env_var": "OPENAI_API_KEY",
        "model":   "gpt-4o",
        "url":     "https://api.openai.com/v1/chat/completions",
        "stream_url": "https://api.openai.com/v1/chat/completions",
        "type":    "openai",
    },
    "groq": {
        "name":    "Groq / LLaMA",
        "env_var": "GROQ_API_KEY",
        "model":   "llama-3.3-70b-versatile",
        "url":     "https://api.groq.com/openai/v1/chat/completions",
        "stream_url": "https://api.groq.com/openai/v1/chat/completions",
        "type":    "openai",
    },
    "gemini": {
        "name":    "Google Gemini",
        "env_var": "GEMINI_API_KEY",
        "model":   "gemini-2.0-flash",
        "url":     "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        "stream_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent",
        "type":    "gemini",
    },
}

_KEY_PREFIXES = {
    "claude":  "sk-ant-",
    "chatgpt": "sk-",
    "groq":    "gsk_",
    "gemini":  "AIza",
}

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
_SYSTEM_PROMPT = (
    "You are a concise, practical Linux/DevOps/networking CLI assistant. "
    "Use plain text. Be direct. No markdown headers. "
    "For commands, use code blocks with backticks only."
)

def _load_config() -> dict:
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

_cfg = _load_config()

def _get_api_key(provider_id: str) -> str:
    p = AI_PROVIDERS.get(provider_id, {})
    saved = _cfg.get("keys", {}).get(provider_id, "")
    if saved:
        return saved
    return os.environ.get(p.get("env_var", ""), "")

def _validate_key(provider_id: str, key: str) -> tuple:
    if not key:
        return False, "no key set"
    prefix = _KEY_PREFIXES.get(provider_id, "")
    if prefix and not key.startswith(prefix):
        others = {pid: pfx for pid, pfx in _KEY_PREFIXES.items()
                  if pid != provider_id and key.startswith(pfx)}
        if others:
            wrong = ", ".join(others.keys())
            return False, f"key looks like a {wrong} key (prefix '{key[:8]}...')"
        return True, f"unusual key prefix '{key[:6]}...'"
    return True, ""

def _active_provider_id() -> str:
    chosen = _cfg.get("active_provider", "")
    if chosen and chosen in AI_PROVIDERS:
        key = _get_api_key(chosen)
        valid, _ = _validate_key(chosen, key)
        if valid:
            return chosen
    for pid in ["groq", "claude", "chatgpt", "gemini"]:
        key = _get_api_key(pid)
        valid, _ = _validate_key(pid, key)
        if valid:
            return pid
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# Streaming AI  ──  one unified function, provider-aware
# ─────────────────────────────────────────────────────────────────────────────

def _make_https_conn(url: str):
    """Return (http.client.HTTPSConnection, path_with_query)"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(parsed.netloc, context=ctx, timeout=45)
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query
    return conn, path

def _stream_anthropic(provider: dict, api_key: str, prompt: str):
    """Yield text chunks from Anthropic streaming SSE."""
    payload = json.dumps({
        "model": provider["model"],
        "max_tokens": 1024,
        "stream": True,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    conn, path = _make_https_conn(provider["stream_url"])
    conn.request("POST", path, body=payload, headers={
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "User-Agent": _UA,
    })
    resp = conn.getresponse()
    if resp.status != 200:
        body = resp.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")

    buf = b""
    while True:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode(errors="replace").strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    obj = json.loads(data)
                    delta = obj.get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        yield text
                except json.JSONDecodeError:
                    pass

def _stream_openai_compat(provider: dict, api_key: str, prompt: str):
    """Yield text chunks from OpenAI-compatible streaming SSE (also Groq)."""
    payload = json.dumps({
        "model": provider["model"],
        "max_tokens": 1024,
        "stream": True,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    }).encode()

    conn, path = _make_https_conn(provider["stream_url"])
    conn.request("POST", path, body=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": _UA,
    })
    resp = conn.getresponse()
    if resp.status != 200:
        body = resp.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")

    buf = b""
    while True:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode(errors="replace").strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    obj = json.loads(data)
                    delta = obj["choices"][0].get("delta", {})
                    text = delta.get("content", "")
                    if text:
                        yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

def _stream_gemini(provider: dict, api_key: str, prompt: str):
    """Yield text chunks from Gemini streaming (alt=sse)."""
    url = provider["stream_url"] + f"?key={api_key}&alt=sse"
    payload = json.dumps({
        "contents": [{"parts": [{"text": f"{_SYSTEM_PROMPT}\n\n{prompt}"}]}],
        "generationConfig": {"maxOutputTokens": 1024},
    }).encode()

    conn, path = _make_https_conn(url)
    conn.request("POST", path, body=payload, headers={
        "Content-Type": "application/json",
        "User-Agent": _UA,
    })
    resp = conn.getresponse()
    if resp.status != 200:
        body = resp.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {resp.status}: {body[:300]}")

    buf = b""
    while True:
        chunk = resp.read(256)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode(errors="replace").strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    obj = json.loads(data)
                    parts = (obj.get("candidates", [{}])[0]
                                .get("content", {})
                                .get("parts", []))
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

def ask_ai_stream(prompt: str):
    """
    Stream AI response to stdout.
    Returns the full accumulated text string.
    """
    pid = _active_provider_id()
    if not pid:
        lines = [
            c("  No AI provider configured.", "yellow"),
            c("  Set one of these environment variables:", "dim"),
        ]
        for p in AI_PROVIDERS.values():
            lines.append(f"    export {p['env_var']}=your_key_here")
        lines.append(c("  Or use: :ai key <provider> <your_key>", "dim"))
        msg = "\n".join(lines)
        print(msg)
        return msg

    provider = AI_PROVIDERS[pid]
    api_key  = _get_api_key(pid)

    print(c(f"\n  ◎ {provider['name']} ", "cyan") + c("▸ ", "blue"), end="", flush=True)

    full_text = []
    col = 0
    try:
        if provider["type"] == "anthropic":
            gen = _stream_anthropic(provider, api_key, prompt)
        elif provider["type"] == "openai":
            gen = _stream_openai_compat(provider, api_key, prompt)
        elif provider["type"] == "gemini":
            gen = _stream_gemini(provider, api_key, prompt)
        else:
            print(c(f"  Unknown provider type: {provider['type']}", "red"))
            return ""

        for chunk in gen:
            full_text.append(chunk)
            # Print with 2-space indent after newlines
            for ch in chunk:
                if ch == "\n":
                    print()
                    print("  ", end="", flush=True)
                    col = 2
                else:
                    print(ch, end="", flush=True)
                    col += 1

        print("\n")

    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        if e.code == 401:
            print(c(f"\n  ✗ Auth error 401 — invalid API key for '{pid}'.", "red"))
            print(c(f"    Fix: :ai key {pid} YOUR_CORRECT_KEY", "yellow"))
        elif e.code == 429:
            print(c("\n  ✗ Rate limit (429) — too many requests. Wait a moment.", "yellow"))
        elif e.code == 403 and ("1010" in body or "cloudflare" in body.lower()):
            print(c("\n  ✗ Cloudflare blocked (403/1010).", "red"))
            print(c("    Try a VPN or: :ai set groq", "yellow"))
        else:
            print(c(f"\n  ✗ API error {e.code}: {body[:200]}", "red"))
    except Exception as e:
        err = str(e)
        if "401" in err or "Unauthorized" in err:
            print(c(f"\n  ✗ Auth error — check your API key for '{pid}'.", "red"))
            print(c(f"    Fix: :ai key {pid} YOUR_CORRECT_KEY", "yellow"))
        else:
            print(c(f"\n  ✗ Streaming error: {err}", "red"))

    return "".join(full_text)

def ai_status() -> str:
    active = _active_provider_id()
    lines  = [c("  AI PROVIDERS", "yellow", "bold"), separator()]
    for pid, p in AI_PROVIDERS.items():
        key         = _get_api_key(pid)
        valid, warn = _validate_key(pid, key)
        masked      = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else ("set" if key else "—")
        is_active   = (pid == active)

        if is_active:
            status = c("✓  active ", "green")
        elif valid:
            status = c("✓  ready  ", "cyan")
        elif key and not valid:
            status = c("⚠  bad key", "yellow")
        else:
            status = c("✗  no key ", "red")

        indicator = c("►", "yellow", "bold") if is_active else " "
        line = (f"  {indicator} {c(pid, 'cyan'):<14} {status}  "
                f"key={c(masked, 'dim')}  ({p['name']})")
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
    lines.append(c("    :ai key <provider> <key> – save a key  (~/.joocli_config.json)", "dim"))
    lines.append(c("    :ai models               – list available models per provider", "dim"))
    return "\n".join(lines)

def ai_set_provider(pid: str) -> str:
    pid = pid.lower().strip()
    if pid not in AI_PROVIDERS:
        valid = ", ".join(AI_PROVIDERS.keys())
        return c(f"  Unknown provider '{pid}'. Valid: {valid}", "red")
    _cfg["active_provider"] = pid
    _save_config(_cfg)
    p    = AI_PROVIDERS[pid]
    key  = _get_api_key(pid)
    valid, warn = _validate_key(pid, key)
    if not key:
        return (c(f"  Switched to {p['name']}.\n", "green") +
                c(f"  ⚠  No key found. Set it with:\n", "yellow") +
                c(f"     :ai key {pid} YOUR_KEY\n  or export {p['env_var']}=YOUR_KEY", "dim"))
    if not valid:
        return (c(f"  Switched to {p['name']}.\n", "green") +
                c(f"  ⚠  Warning: {warn}\n", "yellow") +
                c(f"     Use: :ai key {pid} YOUR_{pid.upper()}_KEY", "dim"))
    return c(f"  Switched to {p['name']} ✓  (streaming enabled)", "green")

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
                c(f"     Use env var instead: export {AI_PROVIDERS[pid]['env_var']}=your_key", "dim"))
    if "keys" not in _cfg:
        _cfg["keys"] = {}
    _cfg["keys"][pid] = key
    _save_config(_cfg)
    msg = c(f"  Key for '{pid}' saved ✓", "green")
    if warn:
        msg += "\n" + c(f"  Note: {warn}", "yellow")
    return msg

def ai_list_models() -> str:
    lines = [c("  AVAILABLE MODELS", "yellow", "bold"), separator()]
    active = _active_provider_id()
    for pid, p in AI_PROVIDERS.items():
        mark = c(" ◄ active", "green") if pid == active else ""
        lines.append(f"  {c(pid, 'cyan'):<14} {c(p['model'], 'white')}{mark}")
    lines.append("")
    lines.append(c("  To change model, edit ~/.joocli_config.json  or submit a PR.", "dim"))
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Command knowledge base  (50+ commands)
# ─────────────────────────────────────────────────────────────────────────────
COMMAND_DOCS = {
    # ── File & directory ──────────────────────────────────────────────────────
    "ls":    {"desc": "List directory contents",
               "flags": {"-l": "long format", "-a": "show hidden", "-h": "human sizes",
                         "-R": "recursive", "-t": "sort by time", "-S": "sort by size",
                         "--color": "colorize output"},
               "example": "ls -lah /var/log"},
    "cd":    {"desc": "Change working directory",
               "flags": {"-": "go to previous directory", "~": "go home"},
               "example": "cd ~/projects"},
    "pwd":   {"desc": "Print current working directory",
               "flags": {}, "example": "pwd"},
    "mkdir": {"desc": "Make directories",
               "flags": {"-p": "create parents", "-v": "verbose"},
               "example": "mkdir -p /opt/myapp/{logs,data,config}"},
    "rm":    {"desc": "Remove files or directories",
               "flags": {"-r": "recursive", "-f": "force", "-i": "interactive",
                         "-v": "verbose"},
               "example": "rm -rf /tmp/build_cache"},
    "cp":    {"desc": "Copy files or directories",
               "flags": {"-r": "recursive", "-p": "preserve attrs", "-v": "verbose",
                         "-u": "update only newer"},
               "example": "cp -rp /src/app /backup/app_$(date +%F)"},
    "mv":    {"desc": "Move or rename files",
               "flags": {"-v": "verbose", "-n": "no overwrite", "-b": "backup"},
               "example": "mv oldname.txt newname.txt"},
    "ln":    {"desc": "Create hard or symbolic links",
               "flags": {"-s": "symbolic link", "-f": "force", "-v": "verbose"},
               "example": "ln -s /opt/node/bin/node /usr/local/bin/node"},
    "touch": {"desc": "Create empty file or update timestamp",
               "flags": {"-t": "set specific time", "-a": "access time only"},
               "example": "touch newfile.txt"},
    "cat":   {"desc": "Display file contents",
               "flags": {"-n": "number lines", "-A": "show special chars", "-s": "squeeze blanks"},
               "example": "cat -n file.txt"},
    "less":  {"desc": "View file with pager (q to quit)",
               "flags": {"-N": "line numbers", "-S": "no line wrap", "-F": "auto-quit if small"},
               "example": "less +G /var/log/syslog"},
    "head":  {"desc": "Output first N lines",
               "flags": {"-n": "number of lines", "-c": "number of bytes"},
               "example": "head -n 50 app.log"},
    "tail":  {"desc": "Output last N lines",
               "flags": {"-n": "number of lines", "-f": "follow in real-time",
                         "-F": "follow by name (survives rotation)"},
               "example": "tail -f /var/log/syslog"},
    "find":  {"desc": "Search for files/dirs",
               "flags": {"-name": "by name", "-type": "f=file d=dir l=link",
                         "-mtime": "modified N days", "-size": "filter by size",
                         "-perm": "by permissions", "-exec": "run on results",
                         "-not": "negate condition"},
               "example": "find . -name '*.log' -mtime +7 -exec rm {} \\;"},
    "locate":{"desc": "Find files by name (uses database)",
               "flags": {"-i": "case insensitive", "-c": "count", "-r": "regex"},
               "example": "locate -i '*.conf' | grep nginx"},
    "stat":  {"desc": "Display file/filesystem status",
               "flags": {"-f": "filesystem info", "-c": "custom format"},
               "example": "stat /etc/passwd"},
    "file":  {"desc": "Determine file type",
               "flags": {"-b": "brief (no filename)", "-i": "MIME type"},
               "example": "file /usr/bin/python3"},
    "chmod": {"desc": "Change file permissions",
               "flags": {"-R": "recursive", "+x": "add execute", "-x": "remove execute",
                         "755": "rwxr-xr-x", "644": "rw-r--r--", "600": "rw-------"},
               "example": "chmod +x script.sh && chmod 644 config.yaml"},
    "chown": {"desc": "Change file owner and group",
               "flags": {"-R": "recursive", "--from": "only if current owner matches"},
               "example": "chown -R www-data:www-data /var/www/html"},
    "df":    {"desc": "Disk space usage by filesystem",
               "flags": {"-h": "human-readable", "-T": "filesystem type",
                         "-i": "inode info", "--total": "grand total"},
               "example": "df -hT"},
    "du":    {"desc": "Directory/file disk usage",
               "flags": {"-h": "human-readable", "-s": "summarize",
                         "-d": "max depth", "--exclude": "exclude pattern"},
               "example": "du -sh * | sort -hr | head -20"},
    # ── Text processing ───────────────────────────────────────────────────────
    "grep":  {"desc": "Search text with patterns",
               "flags": {"-i": "ignore case", "-r": "recursive", "-n": "line numbers",
                         "-v": "invert match", "-l": "filenames only", "-c": "count",
                         "-E": "extended regex", "-P": "Perl regex", "-A": "lines after",
                         "-B": "lines before", "-C": "context lines", "-o": "only match"},
               "example": "grep -rn --include='*.py' 'TODO\\|FIXME' ./src"},
    "awk":   {"desc": "Pattern scanning & text processing",
               "flags": {"-F": "field separator", "NR": "row number", "NF": "num fields",
                         "$0": "whole line", "$1": "1st field", "BEGIN": "before file",
                         "END": "after file", "print": "output", "printf": "formatted output"},
               "example": "awk -F: 'NR>1 {print $1, $3}' /etc/passwd"},
    "sed":   {"desc": "Stream editor",
               "flags": {"-i": "in-place", "-n": "suppress default output",
                         "-e": "add script", "s/a/b/g": "substitute", "d": "delete",
                         "p": "print", "/pat/": "address"},
               "example": "sed -i.bak 's/localhost/0.0.0.0/g' config.yaml"},
    "sort":  {"desc": "Sort lines of text",
               "flags": {"-r": "reverse", "-n": "numeric", "-k": "sort by column",
                         "-t": "field separator", "-u": "unique", "-h": "human numeric"},
               "example": "sort -t',' -k2 -rn data.csv | head -10"},
    "uniq":  {"desc": "Report or omit repeated lines",
               "flags": {"-c": "count occurrences", "-d": "only duplicates",
                         "-u": "only unique", "-i": "ignore case"},
               "example": "sort access.log | uniq -c | sort -rn | head -20"},
    "wc":    {"desc": "Count lines, words, characters",
               "flags": {"-l": "lines", "-w": "words", "-c": "bytes", "-m": "chars"},
               "example": "find . -name '*.py' | xargs wc -l | tail -1"},
    "cut":   {"desc": "Extract columns from text",
               "flags": {"-d": "delimiter", "-f": "fields", "-c": "characters"},
               "example": "cut -d: -f1,3 /etc/passwd"},
    "tr":    {"desc": "Translate or delete characters",
               "flags": {"-d": "delete chars", "-s": "squeeze repeats", "-c": "complement"},
               "example": "echo 'Hello World' | tr '[:upper:]' '[:lower:]'"},
    "paste": {"desc": "Merge lines of files side by side",
               "flags": {"-d": "delimiter", "-s": "serial"},
               "example": "paste -d',' names.txt scores.txt"},
    "tee":   {"desc": "Read stdin, write stdout and files",
               "flags": {"-a": "append mode"},
               "example": "make 2>&1 | tee build.log"},
    "xargs": {"desc": "Build and run commands from stdin",
               "flags": {"-I{}": "placeholder", "-P": "parallel jobs",
                         "-n": "max args per cmd", "-0": "null-delimited",
                         "-r": "no run if empty"},
               "example": "find . -name '*.tmp' -print0 | xargs -0 rm -f"},
    # ── Processes ────────────────────────────────────────────────────────────
    "ps":    {"desc": "Snapshot of current processes",
               "flags": {"aux": "all processes with user/cpu/mem",
                         "-ef": "full format", "--sort": "e.g. --sort=-%cpu",
                         "-p": "by PID", "-u": "by user"},
               "example": "ps aux --sort=-%mem | head -15"},
    "top":   {"desc": "Live system process monitor",
               "flags": {"-b": "batch mode", "-n": "iterations",
                         "-u": "filter user", "-d": "refresh delay"},
               "example": "top -b -n 1 | head -25"},
    "htop":  {"desc": "Interactive process viewer (install: apt/yum install htop)",
               "flags": {"-u": "filter user", "-p": "filter PIDs", "-d": "delay"},
               "example": "htop -u www-data"},
    "kill":  {"desc": "Send signal to process by PID",
               "flags": {"-9": "SIGKILL (force stop)", "-15": "SIGTERM (graceful)",
                         "-1": "SIGHUP (reload)", "-l": "list all signals"},
               "example": "kill -15 $(lsof -t -i:8080)"},
    "pkill": {"desc": "Kill processes by name pattern",
               "flags": {"-f": "match full command", "-u": "by user",
                         "-9": "SIGKILL", "-l": "list matched"},
               "example": "pkill -9 -f 'python3 worker.py'"},
    "killall":{"desc": "Kill all processes by exact name",
                "flags": {"-9": "force", "-u": "by user", "-i": "interactive",
                           "-q": "quiet", "-v": "verbose"},
                "example": "killall -9 node"},
    "nice":  {"desc": "Run command with modified priority",
               "flags": {"-n": "niceness value (-20 to 19)"},
               "example": "nice -n 10 python3 heavy_script.py"},
    "nohup": {"desc": "Run command immune to hangups",
               "flags": {"&": "send to background"},
               "example": "nohup python3 server.py > server.log 2>&1 &"},
    "jobs":  {"desc": "List background jobs in shell",
               "flags": {"-l": "with PIDs", "-r": "running only", "-s": "stopped only"},
               "example": "jobs -l"},
    "bg":    {"desc": "Resume a stopped job in background",
               "flags": {"%N": "job number"},
               "example": "bg %1"},
    "fg":    {"desc": "Bring background job to foreground",
               "flags": {"%N": "job number"},
               "example": "fg %1"},
    # ── Network ──────────────────────────────────────────────────────────────
    "ping":  {"desc": "Test host reachability (ICMP)",
               "flags": {"-c": "packet count (e.g. -c 4)", "-i": "interval secs",
                         "-W": "timeout secs", "-s": "packet size bytes",
                         "-q": "quiet summary only", "-t": "TTL"},
               "example": "ping -c 4 -W 2 8.8.8.8"},
    "traceroute":{"desc": "Trace route to host",
                   "flags": {"-n": "numeric IPs (no DNS)", "-w": "wait secs per probe",
                              "-m": "max hops", "-q": "probes per hop",
                              "-I": "use ICMP", "-T": "use TCP SYN"},
                   "example": "traceroute -n -m 20 8.8.8.8"},
    "tracepath":{"desc": "Trace path to host (no root needed)",
                  "flags": {"-n": "numeric", "-b": "show both"},
                  "example": "tracepath -n google.com"},
    "mtr":   {"desc": "My traceroute — combines ping + traceroute",
               "flags": {"--report": "non-interactive report", "-n": "numeric",
                         "-c": "packet count", "--tcp": "use TCP", "--udp": "use UDP",
                         "-P": "port for TCP/UDP"},
               "example": "mtr --report -n -c 10 8.8.8.8"},
    "dig":   {"desc": "DNS lookup tool",
               "flags": {"+short": "concise output", "+trace": "trace delegation",
                         "-x": "reverse lookup", "@server": "use specific nameserver",
                         "A": "IPv4 record", "AAAA": "IPv6", "MX": "mail",
                         "NS": "nameservers", "TXT": "text", "SOA": "authority",
                         "CNAME": "alias"},
               "example": "dig +short MX gmail.com && dig @8.8.8.8 +trace google.com"},
    "nslookup":{"desc": "Query DNS nameservers",
                 "flags": {"-type=": "record type (A, MX, NS, TXT)",
                            "-server": "specify DNS server"},
                 "example": "nslookup -type=MX google.com 8.8.8.8"},
    "host":  {"desc": "DNS hostname to IP lookup",
               "flags": {"-t": "record type", "-a": "all records", "-v": "verbose"},
               "example": "host -t MX gmail.com"},
    "whois": {"desc": "Domain/IP registration info",
               "flags": {"-H": "no legal disclaimers"},
               "example": "whois google.com"},
    "curl":  {"desc": "Transfer data from/to a server",
               "flags": {"-X": "HTTP method", "-H": "add header", "-d": "POST data",
                         "-o": "output file", "-O": "save with original filename",
                         "-s": "silent", "-S": "show errors in silent mode",
                         "-L": "follow redirects", "-v": "verbose",
                         "-I": "HEAD only (headers)", "-k": "skip TLS verify",
                         "-u": "user:password", "-b": "cookie", "-w": "write-out format"},
               "example": "curl -sS -w '\\nStatus: %{http_code}\\n' https://api.example.com/health"},
    "wget":  {"desc": "Download files from web",
               "flags": {"-q": "quiet", "-O": "output filename", "-c": "continue partial",
                         "-r": "recursive", "-np": "no parent", "-P": "output dir",
                         "--limit-rate": "throttle speed"},
               "example": "wget -q -O /tmp/latest.tar.gz https://example.com/release.tar.gz"},
    "ss":    {"desc": "Socket statistics (modern netstat replacement)",
               "flags": {"-t": "TCP", "-u": "UDP", "-l": "listening only",
                         "-n": "numeric (no DNS)", "-p": "show process",
                         "-a": "all sockets", "-s": "summary statistics",
                         "-4": "IPv4 only", "-6": "IPv6 only"},
               "example": "ss -tlnp"},
    "netstat":{"desc": "Network statistics (legacy)",
                "flags": {"-t": "TCP", "-u": "UDP", "-l": "listening",
                           "-n": "numeric", "-p": "show PID/program",
                           "-r": "routing table", "-s": "statistics"},
                "example": "netstat -tlnp"},
    "lsof":  {"desc": "List open files and network connections",
               "flags": {"-i": "network connections", "-t": "PIDs only",
                         "-p": "by PID", "-u": "by user",
                         "-n": "no hostname resolve", "+D": "directory"},
               "example": "lsof -i :8080 -n"},
    "nmap":  {"desc": "Network exploration and port scanning",
               "flags": {"-sV": "detect service versions", "-sS": "TCP SYN scan",
                         "-sU": "UDP scan", "-p": "port range",
                         "-A": "OS + version + scripts", "--open": "only open ports",
                         "-O": "OS detection", "-Pn": "skip host discovery",
                         "--script": "run NSE script"},
               "example": "nmap -sV --open -p 22,80,443,3306,5432 192.168.1.0/24"},
    "ip":    {"desc": "Show/manipulate routing, network devices, tunnels",
               "flags": {"addr": "show/manage addresses", "route": "routing table",
                         "link": "network interfaces", "neigh": "ARP/neighbor table",
                         "rule": "routing policy", "tun": "tunnels",
                         "show": "display info", "add": "add entry",
                         "del": "delete entry", "flush": "flush entries"},
               "example": "ip addr show && ip route show"},
    "arp":   {"desc": "Display/modify ARP table",
               "flags": {"-a": "display all", "-n": "numeric",
                         "-d": "delete entry", "-s": "add static entry",
                         "-v": "verbose"},
               "example": "arp -a -n"},
    "iptables":{"desc": "Linux IPv4 firewall rules",
                 "flags": {"-L": "list rules", "-n": "numeric", "-v": "verbose",
                            "-A": "append rule", "-D": "delete rule",
                            "-I": "insert rule", "-F": "flush chain",
                            "-t": "table (nat/filter/mangle)"},
                 "example": "iptables -L -n -v --line-numbers"},
    "ufw":   {"desc": "Uncomplicated firewall (Ubuntu)",
               "flags": {"status": "show status", "enable": "enable",
                         "disable": "disable", "allow": "allow port/service",
                         "deny": "deny port", "delete": "remove rule",
                         "verbose": "detailed status"},
               "example": "ufw status verbose && ufw allow 80/tcp"},
    "tcpdump":{"desc": "Capture and analyze network traffic",
                "flags": {"-i": "interface", "-n": "no DNS", "-w": "write pcap file",
                           "-r": "read pcap", "-c": "packet count",
                           "-v": "verbose", "port": "filter by port",
                           "host": "filter by host", "tcp/udp": "filter protocol"},
                "example": "tcpdump -i eth0 -n -c 100 'port 80 or port 443'"},
    # ── System ───────────────────────────────────────────────────────────────
    "ssh":   {"desc": "Secure shell remote login",
               "flags": {"-i": "identity key file", "-p": "port",
                         "-L": "local port forward", "-R": "remote port forward",
                         "-D": "SOCKS proxy", "-N": "no command",
                         "-v": "verbose", "-A": "agent forwarding",
                         "-X": "X11 forwarding", "-o": "option"},
               "example": "ssh -i ~/.ssh/id_ed25519 -p 2222 -L 5432:db:5432 user@bastion"},
    "scp":   {"desc": "Secure copy over SSH",
               "flags": {"-r": "recursive", "-P": "port", "-i": "identity key",
                         "-C": "compress", "-p": "preserve timestamps"},
               "example": "scp -rP 2222 -i ~/.ssh/id_ed25519 ./dist user@host:/var/www/"},
    "rsync": {"desc": "Fast remote/local file sync",
               "flags": {"-a": "archive mode (recurse+links+perms+times)",
                         "-v": "verbose", "-z": "compress",
                         "--delete": "delete extraneous files",
                         "--exclude": "exclude pattern",
                         "--dry-run": "simulate only",
                         "-P": "show progress + partial",
                         "-e": "remote shell command"},
               "example": "rsync -avz --delete -e 'ssh -p 2222' ./src/ user@host:/dest/"},
    "tar":   {"desc": "Archive files",
               "flags": {"-c": "create archive", "-x": "extract",
                         "-v": "verbose", "-f": "archive filename",
                         "-z": "gzip compress", "-j": "bzip2 compress",
                         "-J": "xz compress", "-t": "list contents",
                         "--exclude": "exclude pattern"},
               "example": "tar -czvf backup_$(date +%F).tar.gz --exclude='*.pyc' ./project"},
    "git":   {"desc": "Distributed version control system",
               "flags": {"status": "working tree status", "add": "stage changes",
                         "commit": "record snapshot", "push": "upload to remote",
                         "pull": "fetch and merge", "log": "commit history",
                         "diff": "show unstaged changes", "stash": "stash changes",
                         "rebase": "reapply commits", "cherry-pick": "apply specific commit",
                         "branch": "list/create/delete branches",
                         "checkout": "switch branches/restore",
                         "reset": "undo commits", "tag": "create release tags"},
               "example": "git log --oneline --graph --decorate --all | head -20"},
    "docker":{"desc": "Container lifecycle management",
               "flags": {"ps": "list containers", "images": "list images",
                         "run": "create+start container", "stop": "stop gracefully",
                         "rm": "remove container", "rmi": "remove image",
                         "logs": "view container logs", "exec": "run in container",
                         "build": "build from Dockerfile", "pull": "pull image",
                         "inspect": "detailed info (JSON)", "stats": "live resource usage",
                         "network": "manage networks", "volume": "manage volumes",
                         "compose": "multi-container apps"},
               "example": "docker run -d --name myapp -p 8080:80 --restart=unless-stopped nginx"},
    "systemctl":{"desc": "Manage systemd services",
                  "flags": {"start": "start service", "stop": "stop service",
                             "restart": "restart", "reload": "reload config",
                             "status": "show status", "enable": "enable at boot",
                             "disable": "disable at boot", "is-active": "check if running",
                             "list-units": "list all units", "daemon-reload": "reload unit files"},
                  "example": "systemctl status nginx && systemctl reload nginx"},
    "journalctl":{"desc": "Query and display systemd journal logs",
                   "flags": {"-u": "filter by service unit",
                              "-f": "follow (like tail -f)",
                              "-n": "last N lines",
                              "--since": "e.g. '1 hour ago' or '2025-01-01'",
                              "--until": "end time", "-p": "priority (err/warning/info)",
                              "-b": "current boot", "-k": "kernel messages",
                              "-o": "output format (json/verbose/short)"},
                   "example": "journalctl -u nginx -n 100 --since '30 min ago' -p warning"},
    "cron":  {"desc": "Schedule tasks (crontab syntax)",
               "flags": {"crontab -e": "edit user crontab", "crontab -l": "list crontab",
                         "crontab -r": "remove crontab",
                         "@reboot": "run at boot", "@daily": "run daily"},
               "example": "crontab -e  # add: */5 * * * * /opt/scripts/check.sh >> /var/log/check.log 2>&1"},
    "env":   {"desc": "Show/set environment variables",
               "flags": {"-i": "empty environment", "-u": "unset var"},
               "example": "env | grep -i path | sort"},
    "export":{"desc": "Set environment variable for child processes",
               "flags": {"-n": "unexport", "-p": "print all exported"},
               "example": "export PATH=$PATH:/opt/myapp/bin"},
    "which": {"desc": "Locate a command in PATH",
               "flags": {"-a": "all matches"},
               "example": "which python3 pip3 node"},
    "whereis":{"desc": "Locate binary, source, man pages",
                "flags": {"-b": "binaries only", "-m": "man pages only", "-s": "source only"},
                "example": "whereis nginx"},
    "strace":{"desc": "Trace system calls and signals",
               "flags": {"-p": "attach to PID", "-e": "filter syscalls",
                         "-o": "output file", "-c": "count summary",
                         "-f": "follow forks"},
               "example": "strace -e trace=network -p $(pgrep nginx | head -1)"},
    "ldd":   {"desc": "Print shared library dependencies",
               "flags": {"-v": "verbose"},
               "example": "ldd /usr/bin/python3"},
    "openssl":{"desc": "TLS/SSL toolkit",
                "flags": {"s_client": "TLS client", "x509": "parse cert",
                           "req": "generate CSR", "genrsa": "generate RSA key",
                           "-connect": "host:port", "-showcerts": "show chain"},
                "example": "echo | openssl s_client -connect google.com:443 2>/dev/null | openssl x509 -noout -dates"},
    "free":  {"desc": "Display memory usage",
               "flags": {"-h": "human-readable", "-s": "repeat interval",
                         "-m": "megabytes", "-g": "gigabytes"},
               "example": "free -h"},
    "vmstat":{"desc": "Report virtual memory statistics",
               "flags": {"-a": "active/inactive memory",
                         "-s": "memory stats table", "-d": "disk stats",
                         "-w": "wide output"},
               "example": "vmstat 2 5"},
    "iostat":{"desc": "CPU and I/O statistics",
               "flags": {"-x": "extended stats", "-h": "human-readable",
                         "-d": "disk only", "-c": "CPU only"},
               "example": "iostat -xh 2 3"},
    "uptime":{"desc": "System uptime and load averages",
               "flags": {"-p": "pretty format", "-s": "since boot time"},
               "example": "uptime"},
    "uname": {"desc": "Print system information",
               "flags": {"-a": "all", "-r": "kernel release",
                         "-m": "machine type", "-n": "hostname"},
               "example": "uname -a"},
    "dmesg": {"desc": "Print kernel ring buffer messages",
               "flags": {"-H": "human output", "-T": "timestamps",
                         "-l": "filter level", "--follow": "stream new msgs",
                         "-w": "follow new messages"},
               "example": "dmesg -T -l err,crit | tail -20"},
    "lsblk": {"desc": "List block devices",
               "flags": {"-f": "filesystem info", "-o": "columns",
                         "-t": "tree", "-d": "no dependents"},
               "example": "lsblk -f"},
    "mount": {"desc": "Mount a filesystem",
               "flags": {"-t": "filesystem type", "-o": "options",
                         "-a": "mount all in fstab", "--bind": "bind mount"},
               "example": "mount -o remount,rw /"},
    "umount":{"desc": "Unmount a filesystem",
               "flags": {"-f": "force", "-l": "lazy unmount"},
               "example": "umount -l /mnt/data"},
}

# ─────────────────────────────────────────────────────────────────────────────
# Error patterns
# ─────────────────────────────────────────────────────────────────────────────
ERROR_PATTERNS = [
    (r"command not found",
     "Command missing or not in PATH.\nFix: Check spelling · install package · add to $PATH"),
    (r"permission denied",
     "Insufficient permissions.\nFix: prefix with 'sudo' · check 'ls -la' · fix with 'chmod'"),
    (r"no such file or directory",
     "File or path doesn't exist.\nFix: Check path with 'ls' · use Tab completion · create the file"),
    (r"connection refused",
     "Nothing listening on that port.\nFix: 'systemctl status <svc>' · 'ss -tlnp' to check ports"),
    (r"address already in use",
     "Port already taken.\nFix: 'lsof -i :<PORT> -n' to find PID · 'kill -9 <PID>' to free it"),
    (r"disk quota exceeded|no space left on device",
     "Disk is full.\nFix: 'df -h' to check · 'du -sh * | sort -hr | head' to find large files"),
    (r"broken pipe",
     "Downstream process exited early.\nFix: Usually harmless in pipelines — check the receiving command."),
    (r"too many open files",
     "File descriptor limit hit.\nFix: 'ulimit -n 65536' to raise · check for fd leaks with 'lsof -p <PID>'"),
    (r"segmentation fault|segfault",
     "Program accessed invalid memory.\nFix: Run under 'gdb' · check null pointers / buffer overflows"),
    (r"cannot allocate memory|out of memory|oom",
     "RAM exhausted.\nFix: 'free -h' · 'ps aux --sort=-%mem | head' · add swap or kill memory hogs"),
    (r"read-only file system",
     "Filesystem mounted read-only.\nFix: 'mount -o remount,rw /' · check /etc/fstab for errors"),
    (r"syntax error",
     "Shell script syntax error.\nFix: 'bash -n script.sh' to validate · check quotes & brackets"),
    (r"operation not permitted",
     "Kernel-level restriction.\nFix: Check AppArmor/SELinux · capabilities · container constraints"),
    (r"network is unreachable",
     "No route to destination.\nFix: 'ip addr show' · 'ip route show' · 'ping -c 1 8.8.8.8'"),
    (r"name or service not known|could not resolve",
     "DNS resolution failed.\nFix: 'cat /etc/resolv.conf' · 'dig @8.8.8.8 hostname' · check DNS config"),
    (r"ssl.*certificate|certificate verify failed|ssl.*error",
     "TLS certificate error.\nFix: Check system clock ('date') · 'update-ca-certificates' · curl -k (dev only)"),
    (r"\\r|\\r.*no such file|python.*\\r",
     "Windows CRLF line endings.\nFix: sed -i 's/\\r//' yourfile.py  OR  dos2unix yourfile.py"),
    (r"port \d+ already",
     "Port conflict.\nFix: 'ss -tlnp | grep <PORT>' · stop conflicting service · change app port"),
    (r"host.*unreachable|no route to host",
     "Host unreachable.\nFix: 'ping -c 2 <host>' · 'traceroute -n <host>' · check firewall rules"),
    (r"timeout|timed out",
     "Connection/operation timed out.\nFix: Check target is reachable · firewall rules · increase timeout"),
    (r"refused.*connect|connect refused",
     "Connection refused.\nFix: Service not running? 'systemctl status' · wrong port? 'ss -tlnp'"),
    (r"could not connect|unable to connect",
     "Cannot connect to host.\nFix: 'ping -c 2 <host>' · 'telnet <host> <port>' · check firewall"),
    (r"authentication fail|invalid.*key|wrong.*password|auth.*error",
     "Authentication failed.\nFix: Check credentials · SSH key permissions 'chmod 600 ~/.ssh/id_*' · key agent"),
    (r"invalid option|unrecognized option|unknown option",
     "Invalid command option.\nFix: Check 'man <command>' or ':help <command>' for correct flags"),
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

def run_cmd(cmd_str, timeout=20):
    """Run a shell command, return (stdout, stderr, returncode)."""
    proc = None
    try:
        proc = subprocess.Popen(
            cmd_str, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env={**os.environ, "LANG": "en_US.UTF-8"}
        )
        out, err = proc.communicate(timeout=timeout)
        return out.strip(), err.strip(), proc.returncode
    except subprocess.TimeoutExpired:
        if proc:
            proc.kill()
            proc.communicate()
        return "", "Command timed out", -1
    except KeyboardInterrupt:
        if proc:
            proc.send_signal(__import__("signal").SIGINT)
            try:
                proc.communicate(timeout=2)
            except Exception:
                proc.kill()
                proc.communicate()
        return "", "Interrupted", 130
    except Exception as e:
        return "", str(e), -1

def tool_available(tool: str) -> bool:
    out, _, code = run_cmd(f"command -v {tool} 2>/dev/null")
    return code == 0

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
    tagline = c("  Smart Terminal Assistant  v4.1  ·  AI · Docker · Network", "yellow")
    version = c("  Streaming AI  ·  50+ Commands  ·  Smart Autocomplete  ·  Fuzzy Match", "dim")

    cmds = [
        ("Tab",                 "autocomplete commands, flags & paths"),
        (":help CMD",           "explain any command with flags & examples"),
        (":fix ERR",            "instant fix for common errors"),
        (":ai Q",               "ask AI (streams response in real-time)"),
        (":ai set PROVIDER",    "switch AI: claude / chatgpt / groq / gemini"),
        (":ai key PROV KEY",    "save an API key to config"),
        (":ai status",          "show configured AI providers"),
        (":ai models",          "list models per provider"),
        (":ping HOST",          "ping with clean output"),
        (":trace HOST",         "traceroute to host"),
        (":dns DOMAIN",         "DNS lookup (A/MX/NS/TXT)"),
        (":whois DOMAIN/IP",    "WHOIS registration info"),
        (":arp",                "show ARP/neighbor table"),
        (":net",                "full network interfaces report"),
        (":net scan CIDR",      "scan hosts on a subnet (nmap)"),
        (":net check HOST:PORT","test TCP connectivity"),
        (":ports",              "all listening ports with processes"),
        (":docker",             "Docker containers/images/volumes"),
        (":history N SEARCH",   "search shell history"),
        (":last",               "view last captured error"),
        ("exit",                "leave JooCLI"),
    ]
    cmd_lines = []
    for k, v in cmds:
        cmd_lines.append(
            "  " + c(f"{k:<24}", "yellow", "bold") + c(v, "white", "dim")
        )

    parts = ["\n"]
    parts += [l for l in logo]
    parts += ["", tagline, version, ""]
    parts.append(c("╭─  Commands " + "─" * 54 + "╮", "blue", "dim"))
    parts += cmd_lines
    parts.append(c("╰" + "─" * 66 + "╯", "blue", "dim"))
    parts.append("")
    return "\n".join(parts)

# ─────────────────────────────────────────────────────────────────────────────
# Network Troubleshooter  (greatly expanded)
# ─────────────────────────────────────────────────────────────────────────────

def net_ping(host: str, count: int = 4) -> str:
    """
    Fixed ping — count is always a number, never a word like 'four'.
    Validates host and count strictly.
    """
    # Sanitise host — strip any port or protocol prefix
    host = re.sub(r"^https?://", "", host.strip()).split("/")[0].split(":")[0]
    if not host:
        return c("  Usage: :ping <host>  e.g. :ping 8.8.8.8  or  :ping google.com", "yellow")

    # Validate count is numeric
    try:
        count = int(count)
        if count < 1 or count > 100:
            count = 4
    except (ValueError, TypeError):
        count = 4

    lines = [section_header(f"PING  {host}  (count={count})")]

    # Resolve hostname first so we can show the IP
    try:
        resolved = socket.gethostbyname(host)
        if resolved != host:
            lines.append(c(f"  Resolved: {host} → {resolved}", "dim"))
    except socket.gaierror as e:
        return c(f"  DNS resolution failed for '{host}': {e}\n"
                  "  Fix: check spelling · 'dig +short {host}' · check /etc/resolv.conf", "red")

    out, err, code = run_cmd(
        f"ping -c {count} -W 3 -q {host} 2>&1",
        timeout=count * 4 + 5
    )
    full = out + err
    if not full:
        return c(f"  ping failed — host unreachable or ICMP blocked", "red")

    # Color key lines
    for line in full.splitlines():
        if "packet loss" in line or "statistics" in line:
            loss_m = re.search(r"(\d+)% packet loss", line)
            if loss_m:
                loss = int(loss_m.group(1))
                colour = "green" if loss == 0 else ("yellow" if loss < 50 else "red")
                lines.append(c(f"  {line}", colour))
            else:
                lines.append(c(f"  {line}", "cyan"))
        elif "rtt" in line or "min/avg/max" in line:
            lines.append(c(f"  {line}", "green"))
        elif "error" in line.lower() or "unreachable" in line.lower():
            lines.append(c(f"  {line}", "red"))
        else:
            lines.append(f"  {c(line, 'dim')}")

    return "\n".join(lines)

def net_trace(host: str) -> str:
    """Traceroute to host — tries mtr, then traceroute, then tracepath."""
    host = re.sub(r"^https?://", "", host.strip()).split("/")[0].split(":")[0]
    if not host:
        return c("  Usage: :trace <host>", "yellow")

    lines = [section_header(f"TRACEROUTE  {host}")]

    if tool_available("mtr"):
        lines.append(c("  Using mtr (--report mode)\n", "dim"))
        out, err, code = run_cmd(f"mtr --report -n -c 5 {host} 2>&1", timeout=60)
        tool_used = "mtr"
    elif tool_available("traceroute"):
        out, err, code = run_cmd(f"traceroute -n -w 2 -m 30 {host} 2>&1", timeout=60)
        tool_used = "traceroute"
    elif tool_available("tracepath"):
        out, err, code = run_cmd(f"tracepath -n {host} 2>&1", timeout=60)
        tool_used = "tracepath"
    else:
        return c("  None of mtr/traceroute/tracepath found.\n"
                  "  Install: sudo apt install traceroute  or  sudo apt install mtr", "yellow")

    full = out + err
    for line in full.splitlines():
        if re.search(r"^\s*\d+", line):
            if "???" in line or "* * *" in line or "timeout" in line.lower():
                lines.append(c(f"  {line}", "yellow"))
            else:
                lines.append(f"  {line}")
        elif "traceroute" in line.lower() or "host" in line.lower():
            lines.append(c(f"  {line}", "cyan"))
        else:
            lines.append(f"  {c(line, 'dim')}")

    if not full.strip():
        lines.append(c("  No output — host may be unreachable or hops are firewalled.", "yellow"))

    return "\n".join(lines)

def net_dns(domain: str, record_type: str = "") -> str:
    """Full DNS investigation for a domain."""
    domain = re.sub(r"^https?://", "", domain.strip()).split("/")[0]
    if not domain:
        return c("  Usage: :dns <domain> [type]  e.g. :dns google.com MX", "yellow")

    lines = [section_header(f"DNS  {domain}")]

    if not tool_available("dig"):
        # Fallback to nslookup or host
        tool = "nslookup" if tool_available("nslookup") else "host"
        out, _, _ = run_cmd(f"{tool} {domain} 2>&1")
        for l in out.splitlines():
            lines.append(f"  {l}")
        lines.append(c("\n  Tip: install 'dig' for richer DNS output: sudo apt install dnsutils", "dim"))
        return "\n".join(lines)

    if record_type:
        types = [record_type.upper()]
    else:
        types = ["A", "AAAA", "MX", "NS", "TXT"]

    for rtype in types:
        out, _, code = run_cmd(f"dig +short {rtype} {domain} 2>&1")
        if out:
            lines.append(c(f"\n  {rtype} Records:", "yellow"))
            for r in out.splitlines():
                lines.append(f"  {c('·', 'dim')} {c(r.strip(), 'green')}")
        else:
            lines.append(c(f"\n  {rtype}: (no records)", "dim"))

    # Also show authoritative nameserver
    out, _, _ = run_cmd(f"dig +short SOA {domain} 2>&1")
    if out:
        lines.append(c("\n  SOA (Primary NS):", "yellow"))
        lines.append(f"  {c(out.split()[0] if out.split() else out, 'cyan')}")

    # Reverse lookup if IP
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", domain):
        out, _, _ = run_cmd(f"dig +short -x {domain} 2>&1")
        if out:
            lines.append(c("\n  Reverse PTR:", "yellow"))
            lines.append(f"  {c(out.strip(), 'green')}")

    return "\n".join(lines)

def net_whois(target: str) -> str:
    """WHOIS lookup for a domain or IP."""
    target = re.sub(r"^https?://", "", target.strip()).split("/")[0]
    if not target:
        return c("  Usage: :whois <domain or IP>", "yellow")

    lines = [section_header(f"WHOIS  {target}")]

    if not tool_available("whois"):
        return c("  'whois' not found. Install: sudo apt install whois", "yellow")

    out, err, code = run_cmd(f"whois -H {target} 2>&1", timeout=20)
    full = (out + err).strip()
    if not full:
        return c(f"  No WHOIS data for '{target}'", "yellow")

    # Show key fields only — registrar, creation, expiry, IPs
    important = [
        "registrar", "creation date", "updated date", "expiry date",
        "expires", "registered", "org:", "orgname", "netname",
        "country:", "inetnum", "netrange", "cidr", "nameserver",
        "status:", "admin email", "tech email",
    ]
    printed = 0
    for line in full.splitlines():
        lower = line.lower()
        if any(k in lower for k in important):
            lines.append(f"  {c(line.strip(), 'white')}")
            printed += 1
        if printed >= 25:
            break

    if printed == 0:
        # Fallback: first 30 lines
        for line in full.splitlines()[:30]:
            lines.append(f"  {c(line, 'dim')}")

    lines.append(c("\n  (Showing key fields. Full output: whois " + target + ")", "dim"))
    return "\n".join(lines)

def net_arp() -> str:
    """Display ARP / neighbor table."""
    lines = [section_header("ARP / NEIGHBOR TABLE")]

    # Try 'ip neigh' first (more detailed)
    out, _, code = run_cmd("ip neigh show 2>/dev/null")
    if code == 0 and out:
        lines.append(f"  {'IP ADDRESS':<20} {'INTERFACE':<10} {'MAC ADDRESS':<20} STATE")
        lines.append(c("  " + "─" * 60, "dim"))
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                ip = parts[0]
                dev = ""
                mac = ""
                state = ""
                for i, p in enumerate(parts):
                    if p == "dev" and i+1 < len(parts):
                        dev = parts[i+1]
                    if p == "lladdr" and i+1 < len(parts):
                        mac = parts[i+1]
                    if p in ("REACHABLE","STALE","DELAY","PROBE","FAILED","PERMANENT","NOARP"):
                        state = p
                col = "green" if state == "REACHABLE" else ("yellow" if state in ("STALE","DELAY") else "red")
                lines.append(
                    f"  {c(ip, 'cyan'):<28} {dev:<10} {c(mac or '—', 'white'):<20} {c(state, col)}"
                )
    else:
        # Fallback to arp -a
        out, _, _ = run_cmd("arp -a -n 2>&1")
        for line in out.splitlines():
            lines.append(f"  {line}")

    return "\n".join(lines)

def net_check(target: str) -> str:
    """
    Test TCP connectivity to host:port.
    Also accepts plain host (checks ports 80 and 443) or host:port.
    """
    target = target.strip()
    if not target:
        return c("  Usage: :net check <host:port>  e.g. :net check google.com:443", "yellow")

    # Parse target
    if ":" in target:
        parts = target.rsplit(":", 1)
        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError:
            return c(f"  Invalid port in '{target}'", "red")
        ports = [port]
    else:
        host = target
        ports = [80, 443, 22]

    lines = [section_header(f"TCP CHECK  {host}")]

    # DNS first
    try:
        resolved = socket.gethostbyname(host)
        lines.append(f"  {c('DNS', 'dim'):<16} {host} → {c(resolved, 'green')}")
    except socket.gaierror as e:
        lines.append(c(f"  DNS FAILED: {e}", "red"))
        return "\n".join(lines)

    # TCP probe each port
    for port in ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            start = time.monotonic()
            result = sock.connect_ex((resolved, port))
            elapsed = (time.monotonic() - start) * 1000
            sock.close()
            if result == 0:
                lines.append(
                    f"  {c('TCP', 'dim'):<16} {host}:{c(str(port),'yellow')}  "
                    f"{c('OPEN', 'green', 'bold')}  ({elapsed:.1f} ms)"
                )
            else:
                lines.append(
                    f"  {c('TCP', 'dim'):<16} {host}:{c(str(port),'yellow')}  "
                    f"{c('CLOSED/FILTERED', 'red')}"
                )
        except Exception as e:
            lines.append(c(f"  Port {port}: error — {e}", "red"))

    # HTTP check if port 80 or 443
    for port in [p for p in ports if p in (80, 443)]:
        scheme = "https" if port == 443 else "http"
        url = f"{scheme}://{host}/"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            ctx = ssl.create_default_context() if port == 443 else None
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                lines.append(
                    f"  {c('HTTP', 'dim'):<16} {url}  "
                    f"{c(str(resp.status), 'green')} {resp.reason}"
                )
        except urllib.error.HTTPError as e:
            lines.append(f"  {c('HTTP', 'dim'):<16} {url}  {c(str(e.code), 'yellow')} {e.reason}")
        except Exception as e:
            lines.append(f"  {c('HTTP', 'dim'):<16} {url}  {c(str(e)[:60], 'red')}")

    return "\n".join(lines)

def net_scan(target: str) -> str:
    """Nmap subnet scan for live hosts and open ports."""
    if not tool_available("nmap"):
        return c("  'nmap' not found. Install: sudo apt install nmap", "yellow")

    lines = [section_header(f"SCAN  {target}")]
    lines.append(c("  Running nmap (this may take a moment)...", "dim"))
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()

    out, err, code = run_cmd(
        f"nmap -sV --open -T4 -p 22,80,443,3306,5432,6379,8080,8443,27017 {target} 2>&1",
        timeout=90
    )
    result_lines = [section_header(f"SCAN RESULTS  {target}")]
    if code != 0 or not out:
        result_lines.append(c(f"  Scan failed: {err[:200]}", "red"))
        return "\n".join(result_lines)

    for line in out.splitlines():
        if "Nmap scan report" in line:
            result_lines.append(f"\n  {c(line, 'cyan', 'bold')}")
        elif "/tcp" in line and "open" in line:
            result_lines.append(f"  {c('open', 'green'):<12} {line.strip()}")
        elif "Host is up" in line:
            result_lines.append(c(f"  {line.strip()}", "green"))
        elif "filtered" in line or "closed" in line:
            result_lines.append(c(f"  {line.strip()}", "dim"))
        else:
            result_lines.append(f"  {c(line, 'dim')}")

    return "\n".join(result_lines)

def net_report():
    lines = []
    lines.append(section_header("NETWORK INTERFACES"))

    out, _, code = run_cmd("ip addr show 2>/dev/null")
    if code != 0:
        out, _, _ = run_cmd("ifconfig 2>/dev/null")

    if out:
        for line in out.splitlines():
            m = re.match(r"^\d+:\s+(\S+):", line)
            if m:
                state_m = re.search(r"state (\w+)", line)
                state = state_m.group(1) if state_m else ""
                state_col = "green" if state == "UP" else "red"
                lines.append(
                    f"\n  {c(m.group(1), 'cyan', 'bold')}"
                    + (f"  {c(state, state_col)}" if state else "")
                )
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

    lines.append(section_header("ROUTING TABLE"))
    out, _, _ = run_cmd("ip route show 2>/dev/null || netstat -rn 2>/dev/null | head -10")
    for line in (out.splitlines() if out else []):
        if "default" in line:
            lines.append(c(f"  {line}", "green"))
        else:
            lines.append(f"  {c(line, 'dim')}")

    lines.append(section_header("DNS SERVERS"))
    out, _, _ = run_cmd("cat /etc/resolv.conf 2>/dev/null | grep -E '^nameserver|^search'")
    if out:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                label = parts[0]
                val   = " ".join(parts[1:])
                lines.append(f"  {c(label, 'dim'):<16} {c(val, 'green')}")
    else:
        lines.append(c("  /etc/resolv.conf not readable.", "dim"))

    lines.append(section_header("EXTERNAL IP"))
    out, _, code = run_cmd("curl -s --max-time 5 https://api.ipify.org 2>/dev/null")
    if code == 0 and out:
        lines.append(f"  {c('Public IP', 'dim'):<16} {c(out.strip(), 'green')}")
    else:
        lines.append(c("  Could not determine (no internet?)", "dim"))

    lines.append("")
    lines.append(c("  Network commands: :ping HOST  :trace HOST  :dns DOMAIN  "
                   ":whois DOMAIN  :arp  :net check HOST:PORT  :net scan CIDR", "dim"))
    return "\n".join(lines)

def ports_report():
    lines = [section_header("LISTENING PORTS")]

    out, _, code = run_cmd("ss -tlnp 2>/dev/null")
    if code != 0 or not out:
        out, _, _ = run_cmd("netstat -tlnp 2>/dev/null")

    if out:
        lines.append(f"  {'PROTO':<8} {'LOCAL ADDRESS':<30} {'PROCESS'}")
        lines.append(c("  " + "─" * 62, "dim"))
        for line in out.splitlines()[1:]:
            parts = line.split()
            if not parts or parts[0] in ("Netid", "Proto"):
                continue
            proto = parts[0]
            addr  = parts[3] if len(parts) > 3 else parts[-1]
            proc  = ""
            users_m = re.search(r'users:\(\("([^"]+)"', line)
            if users_m:
                proc = users_m.group(1)
            pid_m = re.search(r"pid=(\d+)", line)
            if pid_m:
                proc += f"[{pid_m.group(1)}]"

            port_m = re.search(r":(\d+)$", addr)
            if port_m:
                port_num = int(port_m.group(1))
                known = {22: "ssh", 80: "http", 443: "https", 3306: "mysql",
                         5432: "postgres", 6379: "redis", 27017: "mongo",
                         8080: "http-alt", 8443: "https-alt", 25: "smtp",
                         53: "dns", 21: "ftp", 3389: "rdp", 5672: "amqp",
                         6443: "k8s-api"}
                svc = known.get(port_num, "")
                addr_str = addr + (f" ({svc})" if svc else "")
                lines.append(
                    f"  {c(proto, 'cyan'):<16} {c(addr_str, 'green'):<38} {c(proc or '—', 'dim')}"
                )
            else:
                lines.append(f"  {c(proto, 'cyan'):<16} {c(addr, 'dim'):<38} {c(proc or '—', 'dim')}")
    else:
        lines.append(c("  Could not retrieve ports (try running as root).", "yellow"))

    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# Docker Inspector
# ─────────────────────────────────────────────────────────────────────────────
def docker_report():
    out, err, code = run_cmd("docker info --format '{{.ServerVersion}}' 2>/dev/null")
    if code != 0:
        return c("  Docker is not running or not installed.", "red")

    lines = [c(f"\n  Docker Engine  v{out}", "cyan", "bold"), separator()]
    lines.append(c("  CONTAINERS", "yellow", "bold"))
    stdout, _, _ = run_cmd(
        "docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}|{{.Ports}}|{{.ID}}'"
    )
    if stdout:
        lines.append(f"  {'NAME':<22} {'STATUS':<22} {'IMAGE':<25} {'PORTS':<28} ID")
        lines.append(c("  " + "─" * 110, "dim"))
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 5:
                continue
            name, status, image, ports, cid = parts[:5]
            if "Up" in status:
                status_str = c(f"{status:<22}", "green")
            elif "Exited" in status:
                status_str = c(f"{status:<22}", "red")
            else:
                status_str = c(f"{status:<22}", "yellow")
            lines.append(
                f"  {c(name, 'bold'):<30} {status_str} {image:<25} "
                f"{c(ports or '—', 'cyan'):<28} {c(cid[:12], 'dim')}"
            )
    else:
        lines.append(c("  No containers found.", "dim"))

    lines += ["", separator(), c("  IMAGES", "yellow", "bold")]
    stdout, _, _ = run_cmd(
        "docker images --format '{{.Repository}}:{{.Tag}}|{{.Size}}|{{.ID}}|{{.CreatedSince}}'"
    )
    if stdout:
        lines.append(f"  {'IMAGE':<40} {'SIZE':<12} {'ID':<14} CREATED")
        lines.append(c("  " + "─" * 80, "dim"))
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 4:
                continue
            img, size, iid, created = parts[:4]
            lines.append(
                f"  {c(img, 'cyan'):<48} {size:<12} {c(iid[:12], 'dim'):<14} {c(created, 'dim')}"
            )
    else:
        lines.append(c("  No images found.", "dim"))

    lines += ["", separator(), c("  NETWORKS", "yellow", "bold")]
    stdout, _, _ = run_cmd("docker network ls --format '{{.Name}}|{{.Driver}}|{{.Scope}}'")
    if stdout:
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 3:
                continue
            lines.append(f"  {c(parts[0], 'white'):<25} driver={c(parts[1], 'cyan')}  scope={c(parts[2], 'dim')}")

    lines += ["", separator(), c("  VOLUMES", "yellow", "bold")]
    stdout, _, _ = run_cmd("docker volume ls --format '{{.Name}}|{{.Driver}}'")
    if stdout:
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 2:
                continue
            lines.append(f"  {c(parts[0], 'white'):<40} driver={c(parts[1], 'cyan')}")
    else:
        lines.append(c("  No volumes.", "dim"))

    lines += ["", c("  :docker logs <name>  :docker exec <name>  :docker inspect <name>", "dim")]
    return "\n".join(lines)

def _docker_fuzzy_container(name: str) -> str:
    """If container 'name' not found, return closest match or empty string."""
    out, _, _ = run_cmd("docker ps -a --format '{{.Names}}' 2>/dev/null", timeout=4)
    all_names = [l.strip() for l in out.splitlines() if l.strip()]
    if not all_names:
        return ""
    ranked = fuzzy_find(name, all_names, cutoff=5)
    return ranked[0] if ranked else ""

def docker_logs(name, tail=50):
    out, err, code = run_cmd(f"docker logs --tail {tail} {name} 2>&1")
    if code != 0:
        suggestion = _docker_fuzzy_container(name)
        msg = c(f"\n  ✗  Container '{name}' not found or error.\n", "red")
        if err:
            msg += c(f"     {err}\n", "dim")
        if suggestion and suggestion != name:
            msg += c(f"\n  Did you mean: ", "yellow") + c(f":docker logs {suggestion}", "cyan") + "\n"
        return msg
    return c(f"  ── Logs: {name} (last {tail} lines) ──\n", "yellow") + (out or c("  (no output)", "dim"))

def docker_exec(name, cmd_str="sh"):
    # Fuzzy check before exec
    out, _, code = run_cmd(f"docker ps -a --format '{{{{.Names}}}}' 2>/dev/null", timeout=4)
    all_names = [l.strip() for l in out.splitlines() if l.strip()]
    if name not in all_names:
        suggestion = _docker_fuzzy_container(name)
        print(c(f"\n  ✗  Container '{name}' not found.", "red"))
        if suggestion:
            print(c(f"  Did you mean: ", "yellow") + c(f":docker exec {suggestion}", "cyan"))
        print()
        return
    print(c(f"\n  Entering container '{name}' (type 'exit' to leave)\n", "cyan"))
    os.system(f"docker exec -it {name} {cmd_str}")

def docker_inspect(name):
    out, err, code = run_cmd(f"docker inspect {name}")
    if code != 0:
        suggestion = _docker_fuzzy_container(name)
        msg = c(f"\n  ✗  Container or image '{name}' not found.\n", "red")
        if suggestion and suggestion != name:
            msg += c(f"  Did you mean: ", "yellow") + c(f":docker inspect {suggestion}", "cyan") + "\n"
        return msg
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
            "", c("  ENV VARS", "yellow"),
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
# Fuzzy / nearest-match helper
# ─────────────────────────────────────────────────────────────────────────────
def _fuzzy_score(a: str, b: str) -> int:
    """Simple edit-distance-like score: lower = closer match."""
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    if b.startswith(a):
        return 1
    # count matching chars in order
    matches = 0
    bi = 0
    for ch in a:
        for i in range(bi, len(b)):
            if b[i] == ch:
                matches += 1
                bi = i + 1
                break
    score = len(a) - matches + abs(len(a) - len(b))
    return score

def fuzzy_find(query: str, candidates: list, cutoff: int = 4) -> list:
    """Return candidates sorted by similarity, filtered to score <= cutoff."""
    if not query:
        return candidates[:10]
    scored = [(c_, _fuzzy_score(query, c_)) for c_ in candidates]
    scored.sort(key=lambda x: x[1])
    return [c_ for c_, s in scored if s <= cutoff]

# ─────────────────────────────────────────────────────────────────────────────
# Live Docker container/image name cache
# ─────────────────────────────────────────────────────────────────────────────
class _DockerCache:
    """Lazily caches container and image names for tab completion."""
    _containers: list = []
    _images:     list = []
    _last_refresh: float = 0
    _TTL: float = 8.0   # seconds between refreshes

    @classmethod
    def _refresh(cls):
        now = time.monotonic()
        if now - cls._last_refresh < cls._TTL:
            return
        cls._last_refresh = now
        try:
            out, _, code = run_cmd(
                "docker ps -a --format '{{.Names}}' 2>/dev/null", timeout=3
            )
            cls._containers = [l.strip() for l in out.splitlines() if l.strip()] if code == 0 else []
        except Exception:
            cls._containers = []
        try:
            out, _, code = run_cmd(
                "docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null", timeout=3
            )
            cls._images = [l.strip() for l in out.splitlines() if l.strip()] if code == 0 else []
        except Exception:
            cls._images = []

    @classmethod
    def containers(cls) -> list:
        cls._refresh()
        return cls._containers

    @classmethod
    def images(cls) -> list:
        cls._refresh()
        return cls._images

# ─────────────────────────────────────────────────────────────────────────────
# Tab completer  — context-aware, 12 completion modes
# ─────────────────────────────────────────────────────────────────────────────
class JooCompleter:

    # All top-level joo commands
    JOO_TOP = [
        ":help", ":fix",
        ":ai", ":ping", ":trace", ":dns", ":whois", ":arp",
        ":net", ":ports", ":docker",
        ":history", ":last", ":clear",
        "exit", "quit",
    ]

    # Sub-commands for each namespace
    _AI_SUBS     = ["set", "key", "status", "models"]
    _NET_SUBS    = ["scan", "check", "dns", "trace", "whois", "arp"]
    _DOCKER_SUBS = ["logs", "exec", "inspect", "stop", "start", "restart", "rm", "rmi", "pull", "stats"]
    _AI_PROVS    = list(AI_PROVIDERS.keys())

    # Common flags for built-in commands (supplement COMMAND_DOCS)
    _EXTRA_FLAGS: dict = {}

    def __init__(self):
        # Build $PATH executable set
        self._path_cmds: list = []
        for p in os.environ.get("PATH", "").split(":"):
            try:
                for f in Path(p).iterdir():
                    if f.is_file() and os.access(f, os.X_OK):
                        self._path_cmds.append(f.name)
            except Exception:
                pass
        self._path_cmds = sorted(set(self._path_cmds))

        # All known commands (docs + PATH) deduplicated
        self._all_cmds = sorted(set(list(COMMAND_DOCS.keys()) + self._path_cmds))

        # Pre-built flat list of every :joo-style completion for first-word matching
        self._joo_flat = (
            self.JOO_TOP
            + [f":ai {s}"      for s in self._AI_SUBS]
            + [f":net {s}"     for s in self._NET_SUBS]
            + [f":docker {s}"  for s in self._DOCKER_SUBS]
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _path_completions(self, text: str) -> list:
        """File/dir path completions, with trailing / for dirs."""
        expanded = os.path.expanduser(text) if text else "."
        base     = os.path.dirname(expanded) or "."
        prefix   = os.path.basename(expanded)
        try:
            entries = os.listdir(base)
        except OSError:
            return []
        results = []
        for e in entries:
            if e.startswith(prefix):
                full = os.path.join(base, e) if base not in (".", "") else e
                results.append(full + "/" if os.path.isdir(full) else full)
        return sorted(results)

    def _flag_completions(self, cmd: str, text: str) -> list:
        """Return flag suggestions for a known command."""
        flags = list(COMMAND_DOCS.get(cmd, {}).get("flags", {}).keys())
        return [f for f in flags if f.startswith(text)]

    def _container_completions(self, text: str) -> list:
        return [n for n in _DockerCache.containers() if n.startswith(text)]

    def _image_completions(self, text: str) -> list:
        return [i for i in _DockerCache.images() if i.startswith(text)]

    # ── core complete ─────────────────────────────────────────────────────────

    def complete(self, text: str, state: int):
        try:
            matches = self._get_matches(text)
            return matches[state] if state < len(matches) else None
        except Exception:
            return None

    def _get_matches(self, text: str) -> list:
        line   = readline.get_line_buffer()
        tokens = line.split()
        # token before cursor (the word being completed)
        cursor_at_space = line.endswith(" ")
        n_tokens = len(tokens)

        # ── MODE 1: first word, starts with ':' ─────────────────────────────
        if not cursor_at_space and n_tokens <= 1 and text.startswith(":"):
            return [x + " " if not x.endswith(" ") else x
                    for x in self._joo_flat if x.startswith(text)]

        # ── MODE 2: ':ai' sub-commands ───────────────────────────────────────
        if n_tokens >= 1 and tokens[0] == ":ai":
            if n_tokens == 1 and cursor_at_space:
                return [s + " " for s in self._AI_SUBS]
            if n_tokens == 2 and not cursor_at_space:
                return [s + " " for s in self._AI_SUBS if s.startswith(text)]
            # ':ai set <provider>' or ':ai key <provider>'
            if n_tokens >= 2 and tokens[1] in ("set", "key"):
                if n_tokens == 2 and cursor_at_space:
                    return [p + " " for p in self._AI_PROVS]
                if n_tokens == 3 and not cursor_at_space:
                    return [p + " " for p in self._AI_PROVS if p.startswith(text)]

        # ── MODE 3: ':net' sub-commands ──────────────────────────────────────
        if n_tokens >= 1 and tokens[0] == ":net":
            if n_tokens == 1 and cursor_at_space:
                return [s + " " for s in self._NET_SUBS]
            if n_tokens == 2 and not cursor_at_space:
                return [s + " " for s in self._NET_SUBS if s.startswith(text)]

        # ── MODE 4: ':docker' sub-commands + container/image names ──────────
        if n_tokens >= 1 and tokens[0] == ":docker":
            if n_tokens == 1 and cursor_at_space:
                return [s + " " for s in self._DOCKER_SUBS]
            if n_tokens == 2 and not cursor_at_space:
                return [s + " " for s in self._DOCKER_SUBS if s.startswith(text)]
            # ':docker <sub> <name>' — container or image name
            if n_tokens >= 2:
                sub = tokens[1].lower()
                if sub in ("logs", "exec", "inspect", "stop", "start", "restart", "rm", "stats"):
                    if n_tokens == 2 and cursor_at_space:
                        return _DockerCache.containers()
                    if n_tokens == 3 and not cursor_at_space:
                        return self._container_completions(text)
                if sub in ("rmi",):
                    if n_tokens == 2 and cursor_at_space:
                        return _DockerCache.images()
                    if n_tokens == 3 and not cursor_at_space:
                        return self._image_completions(text)

        # ── MODE 5: ':help <command>' ────────────────────────────────────────
        if n_tokens >= 1 and tokens[0] == ":help":
            if n_tokens == 1 and cursor_at_space:
                return self._all_cmds[:20]
            if n_tokens == 2 and not cursor_at_space:
                return [c for c in self._all_cmds if c.startswith(text)]

        # ── MODE 6: ':ping / :trace / :dns / :whois / :net check' — hostnames
        if n_tokens >= 1 and tokens[0] in (":ping", ":trace", ":dns", ":whois"):
            if (n_tokens == 1 and cursor_at_space) or (n_tokens == 2 and not cursor_at_space):
                # Offer recently-used hosts from history
                hosts = self._recent_hosts(text)
                return hosts if hosts else []

        # ── MODE 7: first word, no ':' — shell command completion ────────────
        if not cursor_at_space and n_tokens <= 1 and not text.startswith(":"):
            # prefix match first, then fuzzy
            prefix_m = [c for c in self._all_cmds if c.startswith(text)]
            if prefix_m:
                return prefix_m
            # fuzzy fallback (only when text is ≥3 chars to avoid noise)
            if len(text) >= 3:
                return fuzzy_find(text, self._all_cmds, cutoff=3)
            return []

        # ── MODE 8: flags (text starts with '-') ─────────────────────────────
        if text.startswith("-") and tokens:
            cmd0 = tokens[0]
            flags = self._flag_completions(cmd0, text)
            if flags:
                return flags

        # ── MODE 9: git sub-commands ─────────────────────────────────────────
        if n_tokens >= 1 and tokens[0] == "git":
            git_subs = ["add","branch","checkout","cherry-pick","clone","commit",
                        "diff","fetch","init","log","merge","pull","push","rebase",
                        "remote","reset","revert","show","stash","status","tag"]
            if n_tokens == 1 and cursor_at_space:
                return [s + " " for s in git_subs]
            if n_tokens == 2 and not cursor_at_space:
                return [s + " " for s in git_subs if s.startswith(text)]

        # ── MODE 10: systemctl sub-commands ──────────────────────────────────
        if n_tokens >= 1 and tokens[0] == "systemctl":
            sc_subs = ["start","stop","restart","reload","status","enable",
                       "disable","is-active","is-enabled","list-units",
                       "daemon-reload","cat","edit","mask","unmask"]
            if n_tokens == 1 and cursor_at_space:
                return [s + " " for s in sc_subs]
            if n_tokens == 2 and not cursor_at_space:
                return [s + " " for s in sc_subs if s.startswith(text)]

        # ── MODE 11: ssh — recent hosts from ~/.ssh/config + known_hosts ─────
        if n_tokens >= 1 and tokens[0] in ("ssh", "scp", "rsync"):
            if (n_tokens == 1 and cursor_at_space) or (n_tokens == 2 and not cursor_at_space):
                hosts = self._ssh_hosts(text)
                if hosts:
                    return hosts

        # ── MODE 12: path / file completion (default) ────────────────────────
        return self._path_completions(text)

    # ── auxiliary ─────────────────────────────────────────────────────────────

    def _recent_hosts(self, prefix: str = "") -> list:
        """Extract recently-used hostnames from joo + shell history."""
        seen: set = set()
        hosts: list = []
        # known common hosts
        common = ["8.8.8.8", "1.1.1.1", "google.com", "github.com", "cloudflare.com"]
        for h in common:
            if h.startswith(prefix) and h not in seen:
                seen.add(h)
                hosts.append(h)
        # from shell history
        try:
            n = readline.get_current_history_length()
            for i in range(max(1, n - 200), n + 1):
                entry = readline.get_history_item(i) or ""
                for tok in entry.split():
                    tok = re.sub(r"^https?://", "", tok).split("/")[0].split(":")[0]
                    if re.match(r"^[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}$", tok) or \
                       re.match(r"^\d{1,3}(\.\d{1,3}){3}$", tok):
                        if tok.startswith(prefix) and tok not in seen:
                            seen.add(tok)
                            hosts.append(tok)
        except Exception:
            pass
        return hosts[:12]

    def _ssh_hosts(self, prefix: str = "") -> list:
        """Parse ~/.ssh/config and ~/.ssh/known_hosts for hostnames."""
        hosts: list = []
        seen:  set  = set()
        # ~/.ssh/config Hosts
        config = Path.home() / ".ssh" / "config"
        if config.exists():
            try:
                for line in config.read_text(errors="ignore").splitlines():
                    m = re.match(r"^\s*Host\s+(.+)", line, re.IGNORECASE)
                    if m:
                        for h in m.group(1).split():
                            if "*" not in h and h.startswith(prefix) and h not in seen:
                                seen.add(h)
                                hosts.append(h)
            except Exception:
                pass
        # ~/.ssh/known_hosts
        kh = Path.home() / ".ssh" / "known_hosts"
        if kh.exists():
            try:
                for line in kh.read_text(errors="ignore").splitlines()[:100]:
                    h = line.split()[0].split(",")[0].strip("[]").split(":")[0]
                    if h and h.startswith(prefix) and h not in seen:
                        seen.add(h)
                        hosts.append(h)
            except Exception:
                pass
        return hosts[:15]

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
        pid = _active_provider_id()
        if pid:
            print(c(f"  AI: {AI_PROVIDERS[pid]['name']}  ·  streaming enabled  "
                     "(use ':ai status' for all providers)\n", "dim"))
        else:
            print(c("  AI: no provider configured  "
                     "(use ':ai key <provider> <key>' to add one)\n", "yellow"))

    def _setup_readline(self):
        readline.set_completer(self._completer.complete)
        readline.parse_and_bind("tab: complete")
        # On double-Tab, show a clean formatted list instead of readline's raw dump
        readline.set_completion_display_matches_hook(self._display_matches)
        readline.set_completer_delims(" \t\n;|&<>()")
        if HISTORY_FILE.exists():
            try:
                readline.read_history_file(str(HISTORY_FILE))
            except Exception:
                pass
        readline.set_history_length(MAX_HISTORY)

    def _display_matches(self, substitution: str, matches: list, longest: int):
        """Pretty-print completions on double-Tab."""
        if not matches:
            return
        print()  # newline after prompt
        # Categorize
        dirs     = [m for m in matches if m.endswith("/")]
        files    = [m for m in matches if not m.endswith("/") and not m.startswith(":") and "-" not in m[:2]]
        joo_cmds = [m for m in matches if m.startswith(":")]
        other    = [m for m in matches if m not in dirs and m not in files and m not in joo_cmds]

        col_w = max((len(m) for m in matches), default=10) + 2

        def print_row(items, colour):
            line = ""
            per_row = max(1, 72 // col_w)
            for i, item in enumerate(items):
                line += c(f"{item:<{col_w}}", colour)
                if (i + 1) % per_row == 0:
                    print("  " + line)
                    line = ""
            if line:
                print("  " + line)

        if joo_cmds:
            print(c("  joo commands:", "yellow", "dim"))
            print_row(joo_cmds, "cyan")
        if dirs:
            print(c("  directories:", "blue", "dim"))
            print_row(dirs, "blue")
        if files or other:
            print_row(files + other, "white")

        # Reprint the prompt + current input
        print(f"\n{self.PROMPT}", end="", flush=True)
        print(readline.get_line_buffer(), end="", flush=True)

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

        if   token == ":help":    self._cmd_help(arg)
        elif token == ":fix":     self._cmd_fix(arg)
        elif token == ":ai":      self._cmd_ai(arg)
        elif token == ":docker":  self._cmd_docker(arg)
        elif token == ":net":     self._cmd_net(arg)
        elif token == ":ports":   print(f"\n{ports_report()}\n")
        elif token == ":ping":    print(f"\n{self._cmd_ping(arg)}\n")
        elif token == ":trace":   print(f"\n{net_trace(arg)}\n")
        elif token == ":dns":     print(f"\n{self._cmd_dns(arg)}\n")
        elif token == ":whois":   print(f"\n{net_whois(arg)}\n")
        elif token == ":arp":     print(f"\n{net_arp()}\n")
        elif token == ":history": self._cmd_history(arg)
        elif token == ":last":    self._cmd_last()
        elif token == ":clear":   os.system("clear")
        elif token == ":run":     self._cmd_run(arg)
        elif token.startswith(":"):
            print(c(f"\n  Unknown command '{token}'.\n"
                     "  Try: :help :fix :ai :docker :net :ports :ping :trace "
                     ":dns :whois :arp :history :last :clear\n", "yellow"))
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

    # ── command handlers ──────────────────────────────────────────────────────

    def _cmd_ping(self, arg: str) -> str:
        """Parse :ping host [count] — count is always integer."""
        parts = arg.split()
        host  = parts[0] if parts else ""
        # If second arg exists and is numeric, use it; otherwise default
        count = 4
        if len(parts) > 1:
            try:
                count = int(parts[1])
            except ValueError:
                pass  # ignore non-numeric second arg
        return net_ping(host, count)

    def _cmd_dns(self, arg: str) -> str:
        parts  = arg.split()
        domain = parts[0] if parts else ""
        rtype  = parts[1].upper() if len(parts) > 1 else ""
        return net_dns(domain, rtype)

    def _cmd_net(self, arg: str):
        parts = arg.strip().split(None, 1)
        sub   = parts[0].lower() if parts else ""
        rest  = parts[1].strip() if len(parts) > 1 else ""

        if sub == "scan":
            if not rest:
                print(c("  Usage: :net scan <CIDR or host>  e.g. :net scan 192.168.1.0/24", "yellow"))
                return
            print(f"\n{net_scan(rest)}\n")
        elif sub == "check":
            if not rest:
                print(c("  Usage: :net check <host:port>  e.g. :net check github.com:443", "yellow"))
                return
            print(f"\n{net_check(rest)}\n")
        elif sub == "dns":
            print(f"\n{self._cmd_dns(rest)}\n")
        elif sub == "trace":
            print(f"\n{net_trace(rest)}\n")
        elif sub == "whois":
            print(f"\n{net_whois(rest)}\n")
        elif sub == "arp":
            print(f"\n{net_arp()}\n")
        else:
            print(f"\n{net_report()}\n")

    def _cmd_help(self, arg):
        name = arg.strip().lower()
        if not name:
            print(c("  Usage: :help COMMAND  (e.g. :help grep, :help dig, :help nmap)", "yellow"))
            print(c(f"  {len(COMMAND_DOCS)} commands available. Type ':help <name>'.\n", "dim"))
            # Show grouped list
            groups = {
                "Files": ["ls","cd","pwd","mkdir","rm","cp","mv","ln","touch","cat","less","head","tail","find","locate","stat","file"],
                "Perms/Disk": ["chmod","chown","df","du","mount","umount","lsblk"],
                "Text": ["grep","awk","sed","sort","uniq","wc","cut","tr","paste","tee","xargs"],
                "Processes": ["ps","top","htop","kill","pkill","killall","nice","nohup","jobs","bg","fg"],
                "Network": ["ping","traceroute","tracepath","mtr","dig","nslookup","host","whois","curl","wget","ss","netstat","lsof","nmap","ip","arp","iptables","ufw","tcpdump"],
                "SSH/Transfer": ["ssh","scp","rsync","tar"],
                "System": ["git","docker","systemctl","journalctl","cron","env","export","which","whereis","strace","ldd","openssl","free","vmstat","iostat","uptime","uname","dmesg"],
            }
            for grp, cmds in groups.items():
                available = [c_ for c_ in cmds if c_ in COMMAND_DOCS]
                print(f"  {c(grp + ':', 'yellow', 'bold'):<30} {', '.join(c(x,'cyan') for x in available)}")
            print()
            return

        if name in COMMAND_DOCS:
            doc = COMMAND_DOCS[name]
            print(f"\n  {c(name, 'cyan', 'bold')}  —  {doc['desc']}\n")
            print(c("  FLAGS", "yellow"))
            for flag, desc in doc["flags"].items():
                print(f"  {c(flag, 'green'):<30} {c(desc, 'dim')}")
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
            print(c(f"  No pattern matched. Try ':ai fix this error: {text}'", "yellow"))

    def _cmd_ai(self, arg):
        if not arg.strip():
            print(c("  Usage: :ai <question>  |  :ai status  |  :ai set <provider>  "
                     "|  :ai key <provider> <key>  |  :ai models", "yellow"))
            return

        parts = arg.split(None, 2)
        sub   = parts[0].lower()

        if sub == "status":
            print(f"\n{ai_status()}\n")
            return
        if sub == "models":
            print(f"\n{ai_list_models()}\n")
            return
        if sub == "set":
            pid = parts[1].lower() if len(parts) > 1 else ""
            if not pid:
                print(c(f"  Usage: :ai set <provider>   valid: {', '.join(AI_PROVIDERS)}", "yellow"))
                return
            print(f"\n  {ai_set_provider(pid)}\n")
            return
        if sub == "key":
            if len(parts) < 3:
                print(c(f"  Usage: :ai key <provider> <api_key>   providers: {', '.join(AI_PROVIDERS)}", "yellow"))
                return
            print(f"\n  {ai_save_key(parts[1].lower(), parts[2])}\n")
            return

        # Default: stream ask
        ctx = f"Linux/macOS terminal user. {arg}"
        if self.last_error:
            ctx += f"\n\nLast captured error:\n{self.last_error}"
        ask_ai_stream(ctx)

    def _cmd_docker(self, arg):
        parts = arg.strip().split(None, 1)
        sub   = parts[0].lower() if parts else ""
        rest  = parts[1].strip() if len(parts) > 1 else ""

        if sub == "logs":
            tokens = rest.split()
            name = tokens[0] if tokens else ""
            tail = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 50
            if not name:
                print(c("  Usage: :docker logs <container> [lines]", "yellow"))
                self._docker_list_hint()
                return
            print(f"\n{docker_logs(name, tail)}\n")
        elif sub == "exec":
            tokens = rest.split()
            name = tokens[0] if tokens else ""
            sh   = tokens[1] if len(tokens) > 1 else "sh"
            if not name:
                print(c("  Usage: :docker exec <container> [sh|bash]", "yellow"))
                self._docker_list_hint()
                return
            docker_exec(name, sh)
        elif sub == "inspect":
            if not rest:
                print(c("  Usage: :docker inspect <container>", "yellow"))
                self._docker_list_hint()
                return
            print(f"\n{docker_inspect(rest)}\n")
        elif sub in ("stop", "start", "restart", "rm"):
            if not rest:
                print(c(f"  Usage: :docker {sub} <container>", "yellow"))
                self._docker_list_hint()
                return
            # Fuzzy check
            all_names = _DockerCache.containers()
            if rest not in all_names:
                suggestion = _docker_fuzzy_container(rest)
                print(c(f"\n  ✗  Container '{rest}' not found.", "red"))
                if suggestion and suggestion != rest:
                    print(c(f"  Did you mean: ", "yellow") + c(f":docker {sub} {suggestion}", "cyan"))
                print()
                return
            out, err, code = run_cmd(f"docker {sub} {rest}")
            if code == 0:
                print(c(f"\n  ✓  docker {sub} {rest}\n", "green"))
            else:
                print(c(f"\n  ✗  {err}\n", "red"))
        else:
            print(f"\n{docker_report()}\n")

    def _docker_list_hint(self):
        """Print a quick list of available containers."""
        names = _DockerCache.containers()
        if names:
            print(c("  Available containers: ", "dim") + "  ".join(c(n, "cyan") for n in names[:8]))
        print()

    def _cmd_history(self, arg):
        parts  = arg.split(None, 1)
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
        # Use streaming Popen so Ctrl-C is handled cleanly
        proc = None
        out_lines = []
        err_lines = []
        try:
            proc = subprocess.Popen(
                arg, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env={**os.environ, "LANG": "en_US.UTF-8"}
            )
            import select as _select
            import fcntl as _fcntl
            # Make stderr non-blocking
            fd_out = proc.stdout.fileno()
            fd_err = proc.stderr.fileno()
            for fd in (fd_out, fd_err):
                fl = _fcntl.fcntl(fd, _fcntl.F_GETFL)
                _fcntl.fcntl(fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)

            while True:
                rlist, _, _ = _select.select([fd_out, fd_err], [], [], 0.1)
                for fd in rlist:
                    try:
                        data = os.read(fd, 4096).decode(errors="replace")
                        if data:
                            if fd == fd_out:
                                print(data, end="", flush=True)
                                out_lines.append(data)
                            else:
                                err_lines.append(data)
                    except (BlockingIOError, OSError):
                        pass
                if proc.poll() is not None:
                    # Drain remaining output
                    for fd, store, dest in [(fd_out, out_lines, sys.stdout),
                                            (fd_err, err_lines, None)]:
                        try:
                            data = os.read(fd, 65536).decode(errors="replace")
                            if data:
                                store.append(data)
                                if dest:
                                    dest.write(data)
                                    dest.flush()
                        except (BlockingIOError, OSError):
                            pass
                    break

            code = proc.returncode
            err  = "".join(err_lines).strip()

        except KeyboardInterrupt:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            print(c("\n  ^C  interrupted", "yellow"))
            print()
            return
        except Exception as e:
            print(c(f"  Error running command: {e}", "red"))
            print()
            return

        if code not in (0, 130) and err:
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
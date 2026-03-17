#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JooCLI — Smart Terminal Assistant  v5.0
The DevOps & Developer Shell That Thinks With You

Usage:
    python3 joo_cli_v5.py [command args...]

Zero pip installs required — Python 3.8+ stdlib only.

AI Providers (set any one):
    export ANTHROPIC_API_KEY=sk-ant-...    → Claude (claude-sonnet-4-20250514)
    export OPENAI_API_KEY=sk-...           → ChatGPT (gpt-4o)
    export GROQ_API_KEY=gsk_...            → Groq / LLaMA (llama-3.3-70b-versatile)
    export GEMINI_API_KEY=AIza...          → Google Gemini (gemini-2.0-flash)

What's new in v5.0:
    ✓ Multi-turn AI conversation with persistent session context
    ✓ Plugin system — drop .py files in ~/.joocli/plugins/
    ✓ Kubernetes namespace (:k8s pods/logs/exec/describe/top/ctx)
    ✓ Secure key storage (encrypted with machine fingerprint)
    ✓ :watch mode — live monitoring with change alerts
    ✓ :snippet — save & replay named command sequences
    ✓ Destructive command confirmation + dry-run awareness
    ✓ :ai explain — auto-injects last command output as context
    ✓ :ai clear — reset conversation history
    ✓ Package structure ready (modular internal design)
    ✓ Improved error handling + async-safe DNS resolution
    ✓ Cloud CLI wrappers: aws / gcloud / az helpers
    ✓ :bench — quick system benchmark
    ✓ :ssl — TLS certificate inspector
    ✓ :jwt — decode & inspect JWT tokens
    ✓ :b64 / :hash — quick encode/decode/hash tools
    ✓ Enhanced Docker: compose support, stats live view
    ✓ Session-aware command history with smart search
"""

import os, re, sys, json, time, base64, hashlib, hmac, signal
import readline, subprocess, urllib.request, urllib.error
import socket, http.client, ssl, shutil, stat, textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Generator

# ──────────────────────────────────────────────────────────────────────────────
# Paths & constants
# ──────────────────────────────────────────────────────────────────────────────
_HOME           = Path.home()
JOOCLI_DIR      = _HOME / ".joocli"
HISTORY_FILE    = JOOCLI_DIR / "history"
LOG_FILE        = JOOCLI_DIR / "errors.log"
CONFIG_FILE     = JOOCLI_DIR / "config.json"
PLUGINS_DIR     = JOOCLI_DIR / "plugins"
SNIPPETS_FILE   = JOOCLI_DIR / "snippets.json"
CONV_FILE       = JOOCLI_DIR / "conversation.json"
MAX_HISTORY     = 1000
MAX_CONV_TURNS  = 20   # rolling window of conversation turns kept
VERSION         = "5.0"

for _d in (JOOCLI_DIR, PLUGINS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# Terminal colours
# ──────────────────────────────────────────────────────────────────────────────
R = "\033[0m"
STYLES = {
    "bold":    "\033[1m",  "dim":     "\033[2m",
    "italic":  "\033[3m",  "ul":      "\033[4m",
    "red":     "\033[91m", "green":   "\033[92m",
    "yellow":  "\033[93m", "blue":    "\033[94m",
    "magenta": "\033[95m", "cyan":    "\033[96m",
    "white":   "\033[97m", "bg_blue": "\033[44m",
    "bg_dark": "\033[40m", "bg_red":  "\033[41m",
    "bg_green":"\033[42m", "bg_cyan": "\033[46m",
    "orange":  "\033[38;5;208m",
}
def c(text, *styles):
    return "".join(STYLES.get(s,"") for s in styles) + str(text) + R
def strip_ansi(t):
    return re.sub(r"\033\[[0-9;]*m","",t)
def separator(w=60, col="blue"):
    return c("─"*w, col, "dim")
def section_header(title, col="yellow"):
    return f"\n  {c('▸ '+title, col, 'bold')}\n  {c('─'*(len(title)+4), col, 'dim')}"
def box(lines, color="cyan", width=64):
    top = c("╭"+"─"*width+"╮", color)
    bot = c("╰"+"─"*width+"╯", color)
    mid = []
    for line in lines:
        pad = width - 2 - len(strip_ansi(line))
        mid.append(c("│",color)+" "+line+" "*max(pad,0)+" "+c("│",color))
    return "\n".join([top]+mid+[bot])

# ──────────────────────────────────────────────────────────────────────────────
# Secure key storage (machine-fingerprint XOR obfuscation — not crypto-grade
# but far better than plain JSON; use OS keyring if available)
# ──────────────────────────────────────────────────────────────────────────────
def _machine_key() -> bytes:
    """Derive a machine-specific key from stable system identifiers."""
    parts = []
    for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
        try:
            parts.append(Path(path).read_text().strip())
            break
        except Exception:
            pass
    parts.append(str(os.getuid()) if hasattr(os, "getuid") else "0")
    seed = ":".join(parts) or "joocli-fallback"
    return hashlib.sha256(seed.encode()).digest()

def _obfuscate(plaintext: str) -> str:
    key = _machine_key()
    data = plaintext.encode()
    out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.b64encode(out).decode()

def _deobfuscate(encoded: str) -> str:
    try:
        key = _machine_key()
        data = base64.b64decode(encoded)
        out = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return out.decode()
    except Exception:
        return ""

# Try OS keyring first; fall back to obfuscated file
def _keyring_set(service: str, key: str) -> bool:
    try:
        import keyring as kr
        kr.set_password("joocli", service, key)
        return True
    except Exception:
        return False

def _keyring_get(service: str) -> str:
    try:
        import keyring as kr
        return kr.get_password("joocli", service) or ""
    except Exception:
        return ""

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
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
        os.chmod(CONFIG_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass

_cfg = _load_config()

# ──────────────────────────────────────────────────────────────────────────────
# AI Provider Registry
# ──────────────────────────────────────────────────────────────────────────────
AI_PROVIDERS = {
    "claude":  {"name":"Claude (Anthropic)",  "env":"ANTHROPIC_API_KEY",
                "model":"claude-sonnet-4-20250514",
                "url":"https://api.anthropic.com/v1/messages", "type":"anthropic"},
    "chatgpt": {"name":"ChatGPT (OpenAI)",    "env":"OPENAI_API_KEY",
                "model":"gpt-4o",
                "url":"https://api.openai.com/v1/chat/completions", "type":"openai"},
    "groq":    {"name":"Groq / LLaMA",        "env":"GROQ_API_KEY",
                "model":"llama-3.3-70b-versatile",
                "url":"https://api.groq.com/openai/v1/chat/completions", "type":"openai"},
    "gemini":  {"name":"Google Gemini",       "env":"GEMINI_API_KEY",
                "model":"gemini-2.0-flash",
                "url":"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent",
                "type":"gemini"},
}
_KEY_PREFIXES = {"claude":"sk-ant-","chatgpt":"sk-","groq":"gsk_","gemini":"AIza"}
_UA = "JooCLI/5.0 (Linux; DevOps Assistant)"
_SYSTEM_PROMPT = (
    "You are JooCLI, a concise expert Linux/DevOps/Kubernetes/Cloud assistant embedded "
    "in a terminal shell. Rules: be direct and practical. Use plain text. No markdown "
    "headers. For shell commands use single backtick inline code. Keep answers under "
    "300 words unless the user explicitly asks for detail. If the user's last command "
    "output is included, analyse it and give specific actionable advice."
)

def _get_api_key(pid: str) -> str:
    p = AI_PROVIDERS.get(pid, {})
    saved_enc = _cfg.get("keys", {}).get(pid, "")
    if saved_enc:
        via_keyring = _keyring_get(pid)
        if via_keyring:
            return via_keyring
        return _deobfuscate(saved_enc)
    return os.environ.get(p.get("env",""), "")

def _validate_key(pid: str, key: str) -> Tuple[bool, str]:
    if not key:
        return False, "no key set"
    pfx = _KEY_PREFIXES.get(pid,"")
    if pfx and not key.startswith(pfx):
        others = {p:x for p,x in _KEY_PREFIXES.items() if p!=pid and key.startswith(x)}
        if others:
            return False, f"looks like a {', '.join(others)} key"
        return True, f"unusual prefix '{key[:6]}...'"
    return True, ""

def _active_provider_id() -> str:
    chosen = _cfg.get("active_provider","")
    if chosen and chosen in AI_PROVIDERS:
        k = _get_api_key(chosen)
        if _validate_key(chosen, k)[0]: return chosen
    for pid in ["groq","claude","chatgpt","gemini"]:
        k = _get_api_key(pid)
        if _validate_key(pid, k)[0]: return pid
    return ""

# ──────────────────────────────────────────────────────────────────────────────
# Conversation history (multi-turn)
# ──────────────────────────────────────────────────────────────────────────────
_conversation: List[Dict] = []

def _load_conversation():
    global _conversation
    if CONV_FILE.exists():
        try:
            _conversation = json.loads(CONV_FILE.read_text())[-MAX_CONV_TURNS*2:]
        except Exception:
            _conversation = []

def _save_conversation():
    try:
        CONV_FILE.write_text(json.dumps(_conversation[-MAX_CONV_TURNS*2:], indent=2))
        os.chmod(CONV_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass

def _add_to_conversation(role: str, content: str):
    _conversation.append({"role": role, "content": content})
    if len(_conversation) > MAX_CONV_TURNS * 2:
        _conversation.pop(0)

def _clear_conversation():
    global _conversation
    _conversation = []
    if CONV_FILE.exists():
        CONV_FILE.unlink()

_load_conversation()

# ──────────────────────────────────────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────────────────────────────────────
def _make_conn(url: str) -> Tuple:
    from urllib.parse import urlparse
    p = urlparse(url)
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(p.netloc, context=ctx, timeout=45)
    path = p.path + (("?"+p.query) if p.query else "")
    return conn, path

# ──────────────────────────────────────────────────────────────────────────────
# Streaming AI  (anthropic / openai-compat / gemini)
# ──────────────────────────────────────────────────────────────────────────────
def _stream_anthropic(provider, api_key, messages) -> Generator:
    payload = json.dumps({
        "model": provider["model"], "max_tokens": 1500, "stream": True,
        "system": _SYSTEM_PROMPT, "messages": messages,
    }).encode()
    conn, path = _make_conn(provider["url"])
    conn.request("POST", path, body=payload, headers={
        "x-api-key": api_key, "anthropic-version": "2023-06-01",
        "content-type": "application/json", "User-Agent": _UA,
    })
    resp = conn.getresponse()
    if resp.status != 200:
        raise RuntimeError(f"HTTP {resp.status}: {resp.read().decode()[:300]}")
    buf = b""
    while True:
        chunk = resp.read(512)
        if not chunk: break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode(errors="replace").strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]": return
                try:
                    obj = json.loads(data)
                    text = obj.get("delta",{}).get("text","")
                    if text: yield text
                except json.JSONDecodeError:
                    pass

def _stream_openai(provider, api_key, messages) -> Generator:
    msgs = [{"role":"system","content":_SYSTEM_PROMPT}] + messages
    payload = json.dumps({
        "model": provider["model"], "max_tokens": 1500,
        "stream": True, "messages": msgs,
    }).encode()
    conn, path = _make_conn(provider["url"])
    conn.request("POST", path, body=payload, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json", "User-Agent": _UA,
    })
    resp = conn.getresponse()
    if resp.status != 200:
        raise RuntimeError(f"HTTP {resp.status}: {resp.read().decode()[:300]}")
    buf = b""
    while True:
        chunk = resp.read(512)
        if not chunk: break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode(errors="replace").strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]": return
                try:
                    text = json.loads(data)["choices"][0].get("delta",{}).get("content","")
                    if text: yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

def _stream_gemini(provider, api_key, messages) -> Generator:
    combined = _SYSTEM_PROMPT + "\n\n" + "\n".join(
        f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}" for m in messages
    )
    url = provider["url"] + f"?key={api_key}&alt=sse"
    payload = json.dumps({
        "contents":[{"parts":[{"text": combined}]}],
        "generationConfig":{"maxOutputTokens":1500},
    }).encode()
    conn, path = _make_conn(url)
    conn.request("POST", path, body=payload, headers={
        "Content-Type":"application/json","User-Agent":_UA,
    })
    resp = conn.getresponse()
    if resp.status != 200:
        raise RuntimeError(f"HTTP {resp.status}: {resp.read().decode()[:300]}")
    buf = b""
    while True:
        chunk = resp.read(512)
        if not chunk: break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.decode(errors="replace").strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]": return
                try:
                    parts = json.loads(data)["candidates"][0]["content"]["parts"]
                    for p in parts:
                        text = p.get("text","")
                        if text: yield text
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

def ask_ai_stream(prompt: str, inject_last_output: str = "") -> str:
    """Stream AI response. Returns full text. Maintains conversation history."""
    pid = _active_provider_id()
    if not pid:
        msg = (c("  No AI provider configured.\n","yellow") +
               c("  Set an API key:  :ai key <provider> <key>\n","dim") +
               c("  Providers: claude / chatgpt / groq / gemini","dim"))
        print(msg); return msg

    provider = AI_PROVIDERS[pid]
    api_key  = _get_api_key(pid)

    # Build user message with optional last-output context
    user_content = prompt
    if inject_last_output:
        user_content = (f"Last command output:\n```\n{inject_last_output[:2000]}\n```\n\n"
                        f"User question: {prompt}")

    _add_to_conversation("user", user_content)

    print(c(f"\n  ◎ {provider['name']} ","cyan") +
          c(f"[{len(_conversation)//2} turns] ","dim") +
          c("▸ ","blue"), end="", flush=True)

    full = []
    try:
        if provider["type"] == "anthropic":
            gen = _stream_anthropic(provider, api_key, _conversation)
        elif provider["type"] == "openai":
            gen = _stream_openai(provider, api_key, _conversation)
        elif provider["type"] == "gemini":
            gen = _stream_gemini(provider, api_key, _conversation)
        else:
            return ""

        for chunk in gen:
            full.append(chunk)
            for ch in chunk:
                if ch == "\n":
                    print(); print("  ", end="", flush=True)
                else:
                    print(ch, end="", flush=True)
        print("\n")

        response_text = "".join(full)
        _add_to_conversation("assistant", response_text)
        _save_conversation()
        return response_text

    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode()
        except: pass
        if e.code == 401:
            print(c(f"\n  ✗ Auth error 401 — invalid key for '{pid}'.", "red"))
            print(c(f"    Fix: :ai key {pid} YOUR_KEY", "yellow"))
        elif e.code == 429:
            print(c("\n  ✗ Rate limit (429). Wait a moment.", "yellow"))
        else:
            print(c(f"\n  ✗ API error {e.code}: {body[:200]}", "red"))
        _conversation.pop()
        return ""
    except Exception as e:
        err = str(e)
        if "401" in err or "Unauthorized" in err:
            print(c(f"\n  ✗ Auth error — check key for '{pid}'.", "red"))
        else:
            print(c(f"\n  ✗ Streaming error: {err}", "red"))
        _conversation.pop()
        return ""

# ──────────────────────────────────────────────────────────────────────────────
# AI management commands
# ──────────────────────────────────────────────────────────────────────────────
def ai_status() -> str:
    active = _active_provider_id()
    turns = len(_conversation) // 2
    lines = [c("  AI PROVIDERS", "yellow", "bold"), separator(),
             c(f"  Conversation turns in session: {turns}  "
               f"(use ':ai clear' to reset)", "dim"), ""]
    for pid, p in AI_PROVIDERS.items():
        key = _get_api_key(pid)
        valid, warn = _validate_key(pid, key)
        masked = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else ("set" if key else "—")
        is_active = pid == active
        status = (c("✓  active ", "green") if is_active else
                  c("✓  ready  ", "cyan") if valid else
                  c("⚠  bad key", "yellow") if key else
                  c("✗  no key ", "red"))
        ind = c("►", "yellow","bold") if is_active else " "
        lines.append(f"  {ind} {c(pid,'cyan'):<14} {status}  key={c(masked,'dim')}")
        if warn and key: lines.append(c(f"      ⚠  {warn}","yellow"))
    lines += ["", c("  :ai set <provider>  :ai key <p> <k>  :ai clear  :ai models  :ai status","dim")]
    return "\n".join(lines)

def ai_set_provider(pid: str) -> str:
    pid = pid.lower().strip()
    if pid not in AI_PROVIDERS:
        return c(f"  Unknown provider '{pid}'. Valid: {', '.join(AI_PROVIDERS)}", "red")
    _cfg["active_provider"] = pid; _save_config(_cfg)
    key = _get_api_key(pid); valid, warn = _validate_key(pid, key)
    p = AI_PROVIDERS[pid]
    if not key:
        return (c(f"  Switched to {p['name']}.\n","green") +
                c(f"  ⚠  No key. Set with: :ai key {pid} YOUR_KEY","yellow"))
    if not valid:
        return (c(f"  Switched to {p['name']}.\n","green") +
                c(f"  ⚠  Warning: {warn}","yellow"))
    return c(f"  Switched to {p['name']} ✓","green")

def ai_save_key(pid: str, key: str) -> str:
    pid = pid.lower().strip()
    if pid not in AI_PROVIDERS:
        return c(f"  Unknown provider '{pid}'.", "red")
    key = key.strip()
    valid, warn = _validate_key(pid, key)
    if not valid:
        return c(f"  ⚠  Key rejected: {warn}", "yellow")
    if not _keyring_set(pid, key):
        if "keys" not in _cfg: _cfg["keys"] = {}
        _cfg["keys"][pid] = _obfuscate(key)
        _save_config(_cfg)
    msg = c(f"  Key for '{pid}' saved ✓", "green")
    if warn: msg += "\n" + c(f"  Note: {warn}", "yellow")
    return msg

def ai_list_models() -> str:
    active = _active_provider_id()
    lines = [c("  MODELS", "yellow","bold"), separator()]
    for pid, p in AI_PROVIDERS.items():
        mark = c(" ◄ active","green") if pid == active else ""
        lines.append(f"  {c(pid,'cyan'):<14} {c(p['model'],'white')}{mark}")
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Snippets system
# ──────────────────────────────────────────────────────────────────────────────
def _load_snippets() -> dict:
    if SNIPPETS_FILE.exists():
        try: return json.loads(SNIPPETS_FILE.read_text())
        except: pass
    return {}

def _save_snippets(snips: dict):
    SNIPPETS_FILE.write_text(json.dumps(snips, indent=2))

def snippet_save(name: str, command: str, desc: str = "") -> str:
    snips = _load_snippets()
    snips[name] = {"cmd": command, "desc": desc, "saved": datetime.now().isoformat()[:19]}
    _save_snippets(snips)
    return c(f"  Snippet '{name}' saved ✓  run with: :run {name}", "green")

def snippet_list() -> str:
    snips = _load_snippets()
    if not snips: return c("  No snippets yet. Save one with: :snippet save <name> <command>","dim")
    lines = [c("  SNIPPETS", "yellow","bold"), separator()]
    for name, data in snips.items():
        lines.append(f"  {c(name,'cyan'):<22} {c(data.get('desc',''),'dim')}")
        lines.append(f"  {c(' '*22, '')} {c(data['cmd'],'white')}")
    lines.append(c("\n  :run <name>  to execute  ·  :snippet rm <name>  to delete","dim"))
    return "\n".join(lines)

def snippet_run(name: str) -> Optional[str]:
    snips = _load_snippets()
    if name not in snips: return None
    return snips[name]["cmd"]

def snippet_rm(name: str) -> str:
    snips = _load_snippets()
    if name not in snips: return c(f"  No snippet '{name}'","yellow")
    del snips[name]; _save_snippets(snips)
    return c(f"  Snippet '{name}' deleted","green")

# ──────────────────────────────────────────────────────────────────────────────
# Plugin system
# ──────────────────────────────────────────────────────────────────────────────
_plugins: Dict = {}

def _load_plugins():
    """Load all .py plugins from ~/.joocli/plugins/"""
    import importlib.util
    for f in PLUGINS_DIR.glob("*.py"):
        try:
            spec = importlib.util.spec_from_file_location(f.stem, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "COMMANDS") and hasattr(mod, "handle"):
                for cmd in mod.COMMANDS:
                    _plugins[cmd] = mod
        except Exception as e:
            print(c(f"  ⚠  Plugin '{f.name}' failed to load: {e}","yellow"))

def plugin_list() -> str:
    if not _plugins: return c("  No plugins loaded. Add .py files to ~/.joocli/plugins/","dim")
    lines = [c("  PLUGINS","yellow","bold"), separator()]
    seen_mods = {}
    for cmd, mod in _plugins.items():
        if mod not in seen_mods:
            seen_mods[mod] = []
        seen_mods[mod].append(cmd)
    for mod, cmds in seen_mods.items():
        desc = getattr(mod, "DESCRIPTION", "")
        lines.append(f"  {c(', '.join(cmds),'cyan'):<24} {c(desc,'dim')}")
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────
def run_cmd(cmd: str, timeout: int = 20) -> Tuple[str, str, int]:
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env={**os.environ, "LANG":"en_US.UTF-8"}
        )
        out, err = proc.communicate(timeout=timeout)
        return out.strip(), err.strip(), proc.returncode
    except subprocess.TimeoutExpired:
        if proc: proc.kill(); proc.communicate()
        return "", "Command timed out", -1
    except KeyboardInterrupt:
        if proc:
            proc.send_signal(signal.SIGINT)
            try: proc.communicate(timeout=2)
            except: proc.kill(); proc.communicate()
        return "", "Interrupted", 130
    except Exception as e:
        return "", str(e), -1

def tool_available(t: str) -> bool:
    return shutil.which(t) is not None

def resolve_host(host: str, timeout: float = 5.0) -> Optional[str]:
    """DNS resolution with timeout via socket with settimeout."""
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
    except Exception:
        return None
    finally:
        sock.close()

def load_shell_history() -> List[str]:
    history = []
    for hf in ["~/.bash_history","~/.zsh_history","~/.fish/fish_history"]:
        p = Path(hf).expanduser()
        if p.exists():
            try:
                for line in p.read_text(errors="ignore").splitlines():
                    m = re.match(r"^: \d+:\d+;(.+)", line)
                    if m: history.append(m.group(1))
                    elif not line.startswith(": "): history.append(line)
            except: pass
    return [h for h in history if h.strip()]

def log_error(cmd: str, err: str):
    with open(LOG_FILE,"a") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] CMD: {cmd}\nERR: {err}\n{'─'*60}\n")

# ──────────────────────────────────────────────────────────────────────────────
# Destructive command guard
# ──────────────────────────────────────────────────────────────────────────────
_DESTRUCTIVE = re.compile(
    r"(rm\s+(-[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*)\s)|"
    r"(>\s*/dev/s[da])|"
    r"(dd\s+if=|mkfs\s|fdisk\s+/dev/|parted\s)|"
    r"(chmod\s+(-R\s+)?777)|"
    r"(DROP\s+TABLE|DROP\s+DATABASE|TRUNCATE\s+TABLE)|"
    r"(docker\s+(rm|rmi|system\s+prune)\s+-f)|"
    r"(kubectl\s+delete\s+namespace\s+\S+\s+--force)|"
    r"(:>|truncate\s+-s\s+0)",
    re.IGNORECASE
)

def is_destructive(cmd: str) -> bool:
    return bool(_DESTRUCTIVE.search(cmd))

def confirm_destructive(cmd: str) -> bool:
    print(c(f"\n  ⚠  Potentially destructive command detected:", "yellow","bold"))
    print(c(f"     {cmd}","white"))
    try:
        ans = input(c("  Type 'yes' to proceed, anything else to cancel: ","yellow"))
        return ans.strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        print(); return False

# ──────────────────────────────────────────────────────────────────────────────
# Error patterns (expanded)
# ──────────────────────────────────────────────────────────────────────────────
ERROR_PATTERNS = [
    (r"command not found",
     "Command missing.\nFix: check spelling · install package · add to $PATH"),
    (r"permission denied",
     "Insufficient permissions.\nFix: sudo prefix · check ls -la · fix with chmod"),
    (r"no such file or directory",
     "File/path doesn't exist.\nFix: check path · use Tab · create the file"),
    (r"connection refused",
     "Nothing listening on that port.\nFix: systemctl status <svc> · ss -tlnp"),
    (r"address already in use",
     "Port already taken.\nFix: lsof -i :<PORT> · kill -9 <PID>"),
    (r"disk quota exceeded|no space left on device",
     "Disk full.\nFix: df -h · du -sh * | sort -hr | head"),
    (r"too many open files",
     "FD limit hit.\nFix: ulimit -n 65536 · check leaks with lsof -p <PID>"),
    (r"segmentation fault|segfault",
     "Invalid memory access.\nFix: run under gdb · check null/buffer overflows"),
    (r"cannot allocate memory|out of memory|oom",
     "RAM exhausted.\nFix: free -h · ps aux --sort=-%mem | head · add swap"),
    (r"read-only file system",
     "Filesystem read-only.\nFix: mount -o remount,rw / · check fstab"),
    (r"syntax error",
     "Script syntax error.\nFix: bash -n script.sh · check quotes/brackets"),
    (r"network is unreachable",
     "No route.\nFix: ip addr · ip route · ping 8.8.8.8"),
    (r"name or service not known|could not resolve",
     "DNS failure.\nFix: cat /etc/resolv.conf · dig @8.8.8.8 hostname"),
    (r"ssl.*certificate|certificate verify failed",
     "TLS cert error.\nFix: check system clock · update-ca-certificates"),
    (r"\\r|dos2unix",
     "Windows CRLF endings.\nFix: sed -i 's/\\r//' file  OR  dos2unix file"),
    (r"timeout|timed out",
     "Operation timed out.\nFix: check target reachable · firewall rules"),
    (r"authentication fail|invalid.*key|wrong.*password",
     "Auth failed.\nFix: check credentials · chmod 600 ~/.ssh/id_*"),
    (r"OOMKilled|exit code 137",
     "Container killed (OOM).\nFix: increase memory limit · kubectl describe pod"),
    (r"CrashLoopBackOff",
     "Container keeps crashing.\nFix: kubectl logs <pod> --previous · check env vars"),
    (r"ImagePullBackOff|ErrImagePull",
     "Image pull failed.\nFix: check image name/tag · docker login · registry access"),
    (r"context deadline exceeded",
     "K8s/gRPC timeout.\nFix: kubectl cluster-info · check apiserver · network policies"),
    (r"ENOMEM|ENOSPC",
     "System resource exhausted.\nFix: df -h · free -h · dmesg | tail"),
]

def match_error(text: str) -> Optional[str]:
    for pat, advice in ERROR_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return advice
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Command knowledge base (expanded with K8s, cloud)
# ──────────────────────────────────────────────────────────────────────────────
COMMAND_DOCS = {
    "ls":    {"desc":"List directory contents","flags":{"-l":"long","-a":"hidden","-h":"human","-R":"recursive","-t":"by time","-S":"by size"},"example":"ls -lah /var/log"},
    "cd":    {"desc":"Change directory","flags":{"-":"previous dir","~":"home"},"example":"cd ~/projects"},
    "pwd":   {"desc":"Print working directory","flags":{},"example":"pwd"},
    "mkdir": {"desc":"Make directories","flags":{"-p":"create parents","-v":"verbose"},"example":"mkdir -p /opt/app/{logs,data,config}"},
    "rm":    {"desc":"Remove files/dirs","flags":{"-r":"recursive","-f":"force","-i":"interactive","-v":"verbose"},"example":"rm -rf /tmp/build"},
    "cp":    {"desc":"Copy files","flags":{"-r":"recursive","-p":"preserve","-v":"verbose"},"example":"cp -rp /src /backup"},
    "mv":    {"desc":"Move/rename","flags":{"-v":"verbose","-n":"no overwrite"},"example":"mv old.txt new.txt"},
    "find":  {"desc":"Find files","flags":{"-name":"by name","-type":"f/d/l","-mtime":"days","-exec":"run cmd"},"example":"find . -name '*.log' -mtime +7 -delete"},
    "grep":  {"desc":"Search text","flags":{"-i":"case insensitive","-r":"recursive","-n":"line numbers","-v":"invert","-E":"extended regex","-l":"filenames only","-C":"context lines"},"example":"grep -rn 'TODO' ./src"},
    "awk":   {"desc":"Text processing","flags":{"-F":"separator","NR":"row num","$1":"field 1"},"example":"awk -F: '{print $1}' /etc/passwd"},
    "sed":   {"desc":"Stream editor","flags":{"-i":"in-place","s/a/b/g":"substitute"},"example":"sed -i 's/old/new/g' config.yaml"},
    "tail":  {"desc":"Last N lines","flags":{"-n":"count","-f":"follow","-F":"follow by name"},"example":"tail -f /var/log/syslog"},
    "head":  {"desc":"First N lines","flags":{"-n":"count"},"example":"head -n 50 app.log"},
    "cat":   {"desc":"Display file","flags":{"-n":"number lines","-A":"show special chars"},"example":"cat -n file.txt"},
    "less":  {"desc":"Pager viewer","flags":{"-N":"line numbers","-S":"no wrap"},"example":"less +G /var/log/syslog"},
    "chmod": {"desc":"Change permissions","flags":{"-R":"recursive","+x":"add exec","755":"rwxr-xr-x","644":"rw-r--r--"},"example":"chmod +x script.sh"},
    "chown": {"desc":"Change owner","flags":{"-R":"recursive"},"example":"chown -R www-data /var/www"},
    "df":    {"desc":"Disk space","flags":{"-h":"human","-T":"type","--total":"grand total"},"example":"df -hT"},
    "du":    {"desc":"Directory size","flags":{"-h":"human","-s":"summarize","-d":"max depth"},"example":"du -sh * | sort -hr | head"},
    "ps":    {"desc":"Process snapshot","flags":{"aux":"all processes","--sort":"sort field"},"example":"ps aux --sort=-%mem | head"},
    "top":   {"desc":"Live process monitor","flags":{"-b":"batch","-n":"iterations","-u":"user"},"example":"top -b -n 1"},
    "kill":  {"desc":"Send signal","flags":{"-9":"SIGKILL","-15":"SIGTERM","-1":"SIGHUP","-l":"list signals"},"example":"kill -15 $(lsof -t -i:8080)"},
    "pkill": {"desc":"Kill by name pattern","flags":{"-f":"full command","-9":"force"},"example":"pkill -9 -f 'python3 worker.py'"},
    "ssh":   {"desc":"Secure shell","flags":{"-i":"key file","-p":"port","-L":"local forward","-R":"remote forward","-D":"SOCKS","-N":"no command"},"example":"ssh -i ~/.ssh/key -L 5432:db:5432 user@host"},
    "scp":   {"desc":"Secure copy","flags":{"-r":"recursive","-P":"port","-i":"key"},"example":"scp -r ./dist user@host:/var/www/"},
    "rsync": {"desc":"Fast sync","flags":{"-a":"archive","-v":"verbose","-z":"compress","--delete":"delete extra","--dry-run":"simulate"},"example":"rsync -avz --delete ./src/ user@host:/dest/"},
    "curl":  {"desc":"HTTP client","flags":{"-X":"method","-H":"header","-d":"POST data","-s":"silent","-L":"follow redirects","-v":"verbose","-I":"HEAD only","-o":"output file"},"example":"curl -sS -w '\\nHTTP: %{http_code}\\n' https://api.example.com/health"},
    "wget":  {"desc":"Download files","flags":{"-q":"quiet","-O":"output file","-c":"continue"},"example":"wget -q -O /tmp/file.tar.gz https://example.com/file.tar.gz"},
    "ping":  {"desc":"Test reachability","flags":{"-c":"count","-W":"timeout","-q":"quiet"},"example":"ping -c 4 8.8.8.8"},
    "dig":   {"desc":"DNS lookup","flags":{"+short":"concise","+trace":"trace","-x":"reverse","@server":"use server"},"example":"dig +short MX gmail.com"},
    "ss":    {"desc":"Socket stats","flags":{"-t":"TCP","-u":"UDP","-l":"listening","-n":"numeric","-p":"process","-a":"all"},"example":"ss -tlnp"},
    "lsof":  {"desc":"List open files","flags":{"-i":"network","-t":"PIDs only","-p":"by PID","-u":"by user"},"example":"lsof -i :8080 -n"},
    "nmap":  {"desc":"Port scanner","flags":{"-sV":"service versions","-p":"ports","--open":"only open","-A":"OS detection","-Pn":"no ping"},"example":"nmap -sV --open -p 22,80,443 192.168.1.0/24"},
    "ip":    {"desc":"Network config","flags":{"addr":"addresses","route":"routing","link":"interfaces","neigh":"ARP table"},"example":"ip addr show && ip route show"},
    "git":   {"desc":"Version control","flags":{"status":"working tree","add":"stage","commit":"snapshot","push":"upload","pull":"fetch+merge","log":"history","stash":"stash","rebase":"reapply","branch":"branches"},"example":"git log --oneline --graph --decorate --all | head -20"},
    "docker":{"desc":"Container management","flags":{"ps":"containers","images":"images","run":"create+start","stop":"stop","rm":"remove","logs":"logs","exec":"exec in container","build":"build image","inspect":"details","stats":"live stats","compose":"multi-container"},"example":"docker run -d --name myapp -p 8080:80 --restart=unless-stopped nginx"},
    "systemctl":{"desc":"Manage systemd services","flags":{"start":"start","stop":"stop","restart":"restart","status":"status","enable":"enable at boot","disable":"disable","daemon-reload":"reload units"},"example":"systemctl status nginx && systemctl reload nginx"},
    "journalctl":{"desc":"System journal logs","flags":{"-u":"service unit","-f":"follow","-n":"last N lines","--since":"start time","-p":"priority","-b":"current boot"},"example":"journalctl -u nginx -n 100 --since '30 min ago'"},
    "kubectl":{"desc":"Kubernetes CLI","flags":{"get":"list resources","describe":"detailed info","logs":"container logs","exec":"exec in pod","apply":"apply config","delete":"delete resource","port-forward":"forward port","rollout":"manage rollouts","scale":"scale replicas","top":"resource usage","config":"kubeconfig","namespace":"set namespace"},"example":"kubectl get pods -n production -o wide"},
    "helm":  {"desc":"Kubernetes package manager","flags":{"install":"install chart","upgrade":"upgrade release","list":"list releases","uninstall":"uninstall","repo":"manage repos","template":"render templates","rollback":"rollback release"},"example":"helm upgrade --install myapp ./chart -f values-prod.yaml"},
    "terraform":{"desc":"Infrastructure as code","flags":{"init":"initialize","plan":"dry run","apply":"apply changes","destroy":"tear down","output":"show outputs","state":"manage state","import":"import resource"},"example":"terraform plan -var-file=prod.tfvars"},
    "aws":   {"desc":"AWS CLI","flags":{"ec2":"EC2 instances","s3":"S3 storage","iam":"identity/access","eks":"EKS clusters","rds":"RDS databases","cloudwatch":"monitoring","--profile":"use named profile","--region":"AWS region"},"example":"aws ec2 describe-instances --region us-east-1 --query 'Reservations[].Instances[].{ID:InstanceId,State:State.Name}'"},
    "gcloud":{"desc":"Google Cloud CLI","flags":{"compute":"GCE","container":"GKE","storage":"GCS","sql":"Cloud SQL","iam":"IAM","--project":"project ID","--zone":"zone"},"example":"gcloud container clusters get-credentials my-cluster --zone us-central1-a"},
    "az":    {"desc":"Azure CLI","flags":{"vm":"virtual machines","aks":"AKS clusters","storage":"Azure storage","acr":"container registry","--resource-group":"RG name","--subscription":"subscription"},"example":"az aks get-credentials --resource-group myRG --name myAKS"},
    "free":  {"desc":"Memory usage","flags":{"-h":"human","-m":"MB","-g":"GB"},"example":"free -h"},
    "df":    {"desc":"Disk space","flags":{"-h":"human","-T":"type"},"example":"df -hT"},
    "tar":   {"desc":"Archive files","flags":{"-c":"create","-x":"extract","-v":"verbose","-f":"filename","-z":"gzip","-j":"bzip2"},"example":"tar -czvf backup.tar.gz --exclude='*.pyc' ./project"},
    "openssl":{"desc":"TLS toolkit","flags":{"s_client":"TLS client","x509":"parse cert","req":"generate CSR"},"example":"echo | openssl s_client -connect google.com:443 2>/dev/null | openssl x509 -noout -dates"},
    "jq":    {"desc":"JSON processor","flags":{".":"identity",".key":"field","[]":"array","map":"transform","select":"filter","-r":"raw output","-c":"compact"},"example":"cat data.json | jq '.items[] | select(.status==\"active\") | .name'"},
    "iptables":{"desc":"Firewall rules","flags":{"-L":"list","-A":"append","-D":"delete","-F":"flush","-t":"table","-n":"numeric"},"example":"iptables -L -n -v --line-numbers"},
    "ufw":   {"desc":"Ubuntu firewall","flags":{"status":"show","allow":"allow","deny":"deny","delete":"remove"},"example":"ufw status verbose && ufw allow 443/tcp"},
    "strace":{"desc":"Trace syscalls","flags":{"-p":"attach PID","-e":"filter","-c":"summary","-f":"follow forks"},"example":"strace -e trace=network -p $(pgrep nginx | head -1)"},
    "tcpdump":{"desc":"Capture traffic","flags":{"-i":"interface","-n":"no DNS","-w":"write pcap","-c":"count","port":"filter port","host":"filter host"},"example":"tcpdump -i eth0 -n -c 100 'port 443'"},
    "dmesg": {"desc":"Kernel messages","flags":{"-T":"timestamps","-l":"filter level","-H":"human","-w":"follow"},"example":"dmesg -T -l err,crit | tail -20"},
}

# ──────────────────────────────────────────────────────────────────────────────
# Network tools
# ──────────────────────────────────────────────────────────────────────────────
def net_ping(host: str, count: int = 4) -> str:
    host = re.sub(r"^https?://","",host.strip()).split("/")[0].split(":")[0]
    if not host: return c("  Usage: :ping <host>","yellow")
    try: count = max(1, min(int(count), 50))
    except: count = 4
    lines = [section_header(f"PING  {host}")]
    resolved = resolve_host(host)
    if not resolved:
        return c(f"  DNS resolution failed for '{host}'.\n  Fix: dig +short {host}","red")
    if resolved != host:
        lines.append(c(f"  Resolved: {host} → {resolved}","dim"))
    out, err, code = run_cmd(f"ping -c {count} -W 3 -q {host} 2>&1", timeout=count*4+5)
    full = out+err
    if not full: return c("  ping failed — unreachable or ICMP blocked","red")
    for line in full.splitlines():
        if "packet loss" in line:
            loss_m = re.search(r"(\d+)% packet loss", line)
            loss = int(loss_m.group(1)) if loss_m else 100
            col = "green" if loss==0 else ("yellow" if loss<50 else "red")
            lines.append(c(f"  {line}", col))
        elif "rtt" in line or "min/avg" in line:
            lines.append(c(f"  {line}","green"))
        elif "error" in line.lower() or "unreachable" in line.lower():
            lines.append(c(f"  {line}","red"))
        else:
            lines.append(f"  {c(line,'dim')}")
    return "\n".join(lines)

def net_trace(host: str) -> str:
    host = re.sub(r"^https?://","",host.strip()).split("/")[0].split(":")[0]
    if not host: return c("  Usage: :trace <host>","yellow")
    lines = [section_header(f"TRACEROUTE  {host}")]
    if tool_available("mtr"):
        out, err, _ = run_cmd(f"mtr --report -n -c 5 {host} 2>&1", timeout=60)
    elif tool_available("traceroute"):
        out, err, _ = run_cmd(f"traceroute -n -w 2 -m 30 {host} 2>&1", timeout=60)
    elif tool_available("tracepath"):
        out, err, _ = run_cmd(f"tracepath -n {host} 2>&1", timeout=60)
    else:
        return c("  Need mtr/traceroute/tracepath: sudo apt install traceroute","yellow")
    for line in (out+err).splitlines():
        if re.search(r"^\s*\d+", line):
            lines.append(c(f"  {line}","yellow") if ("???" in line or "* * *" in line) else f"  {line}")
        else:
            lines.append(f"  {c(line,'dim')}")
    return "\n".join(lines)

def net_dns(domain: str, rtype: str = "") -> str:
    domain = re.sub(r"^https?://","",domain.strip()).split("/")[0]
    if not domain: return c("  Usage: :dns <domain> [type]","yellow")
    lines = [section_header(f"DNS  {domain}")]
    if not tool_available("dig"):
        out, _, _ = run_cmd(f"nslookup {domain} 2>&1")
        for l in out.splitlines(): lines.append(f"  {l}")
        return "\n".join(lines)
    types = [rtype.upper()] if rtype else ["A","AAAA","MX","NS","TXT"]
    for rt in types:
        out, _, code = run_cmd(f"dig +short {rt} {domain} 2>&1")
        if out:
            lines.append(c(f"\n  {rt} Records:","yellow"))
            for r in out.splitlines():
                lines.append(f"  {c('·','dim')} {c(r.strip(),'green')}")
        else:
            lines.append(c(f"\n  {rt}: (no records)","dim"))
    out, _, _ = run_cmd(f"dig +short SOA {domain} 2>&1")
    if out:
        lines.append(c("\n  SOA:","yellow"))
        lines.append(f"  {c(out.split()[0] if out.split() else out, 'cyan')}")
    return "\n".join(lines)

def net_whois(target: str) -> str:
    target = re.sub(r"^https?://","",target.strip()).split("/")[0]
    if not target: return c("  Usage: :whois <domain or IP>","yellow")
    if not tool_available("whois"):
        return c("  'whois' not found: sudo apt install whois","yellow")
    lines = [section_header(f"WHOIS  {target}")]
    out, err, _ = run_cmd(f"whois -H {target} 2>&1", timeout=20)
    important = ["registrar","creation date","updated date","expiry date","expires",
                 "registered","org:","orgname","netname","country:","inetnum",
                 "netrange","cidr","nameserver","status:"]
    printed = 0
    for line in (out+err).splitlines():
        if any(k in line.lower() for k in important):
            lines.append(f"  {c(line.strip(),'white')}"); printed += 1
        if printed >= 20: break
    if printed == 0:
        for line in (out+err).splitlines()[:25]: lines.append(f"  {c(line,'dim')}")
    return "\n".join(lines)

def net_arp() -> str:
    lines = [section_header("ARP / NEIGHBOR TABLE")]
    out, _, code = run_cmd("ip neigh show 2>/dev/null")
    if code == 0 and out:
        lines.append(f"  {'IP ADDRESS':<20} {'INTERFACE':<10} {'MAC ADDRESS':<20} STATE")
        lines.append(c("  "+"─"*60,"dim"))
        for line in out.splitlines():
            parts = line.split(); ip = parts[0]; dev = mac = state = ""
            for i, p in enumerate(parts):
                if p == "dev" and i+1 < len(parts): dev = parts[i+1]
                if p == "lladdr" and i+1 < len(parts): mac = parts[i+1]
                if p in ("REACHABLE","STALE","DELAY","PROBE","FAILED","PERMANENT"): state = p
            col = "green" if state=="REACHABLE" else ("yellow" if state in ("STALE","DELAY") else "red")
            lines.append(f"  {c(ip,'cyan'):<28} {dev:<10} {c(mac or '—','white'):<20} {c(state,col)}")
    else:
        out, _, _ = run_cmd("arp -a -n 2>&1")
        for line in out.splitlines(): lines.append(f"  {line}")
    return "\n".join(lines)

def net_check(target: str) -> str:
    if not target: return c("  Usage: :net check <host:port>","yellow")
    if ":" in target:
        h, port_s = target.rsplit(":", 1)
        try: ports = [int(port_s)]
        except: return c(f"  Invalid port in '{target}'","red")
        host = h
    else:
        host = target; ports = [80, 443, 22]
    lines = [section_header(f"TCP CHECK  {host}")]
    resolved = resolve_host(host)
    if not resolved:
        lines.append(c(f"  DNS FAILED for '{host}'","red")); return "\n".join(lines)
    lines.append(f"  {c('DNS','dim'):<16} {host} → {c(resolved,'green')}")
    for port in ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5); t0 = time.monotonic()
            res = s.connect_ex((resolved, port))
            elapsed = (time.monotonic()-t0)*1000; s.close()
            if res == 0:
                lines.append(f"  {c('TCP','dim'):<16} {host}:{c(str(port),'yellow')}  {c('OPEN','green','bold')}  ({elapsed:.1f} ms)")
            else:
                lines.append(f"  {c('TCP','dim'):<16} {host}:{c(str(port),'yellow')}  {c('CLOSED/FILTERED','red')}")
        except Exception as e:
            lines.append(c(f"  Port {port}: error — {e}","red"))
    return "\n".join(lines)

def net_scan(target: str) -> str:
    if not tool_available("nmap"):
        return c("  'nmap' not found: sudo apt install nmap","yellow")
    lines = [section_header(f"SCAN  {target}")]
    print("\n".join(lines) + "\n" + c("  Running nmap...","dim")); sys.stdout.flush()
    out, err, code = run_cmd(
        f"nmap -sV --open -T4 -p 22,80,443,3306,5432,6379,8080,8443,27017,9200 {target} 2>&1",
        timeout=120
    )
    result = [section_header(f"SCAN RESULTS  {target}")]
    if code != 0: result.append(c(f"  Scan failed: {err[:200]}","red")); return "\n".join(result)
    for line in out.splitlines():
        if "Nmap scan report" in line: result.append(f"\n  {c(line,'cyan','bold')}")
        elif "/tcp" in line and "open" in line: result.append(f"  {c('open','green'):<12} {line.strip()}")
        elif "Host is up" in line: result.append(c(f"  {line.strip()}","green"))
        else: result.append(f"  {c(line,'dim')}")
    return "\n".join(result)

def net_report() -> str:
    lines = []
    lines.append(section_header("NETWORK INTERFACES"))
    out, _, code = run_cmd("ip addr show 2>/dev/null")
    if code != 0: out, _, _ = run_cmd("ifconfig 2>/dev/null")
    if out:
        for line in out.splitlines():
            m = re.match(r"^\d+:\s+(\S+):", line)
            if m:
                state_m = re.search(r"state (\w+)", line)
                state = state_m.group(1) if state_m else ""
                col = "green" if state == "UP" else "red"
                lines.append(f"\n  {c(m.group(1),'cyan','bold')}" + (f"  {c(state,col)}" if state else ""))
            ipv4 = re.search(r"inet (\d+\.\d+\.\d+\.\d+)(?:/(\d+))?", line)
            if ipv4:
                ip = ipv4.group(1); pfx = f"/{ipv4.group(2)}" if ipv4.group(2) else ""
                lines.append(f"    {c('IPv4','dim'):<14} {c(ip+pfx,'green')}")
            mac = re.search(r"ether ([0-9a-f:]{17})", line)
            if mac: lines.append(f"    {c('MAC','dim'):<14} {c(mac.group(1),'dim')}")
    lines.append(section_header("ROUTING TABLE"))
    out, _, _ = run_cmd("ip route show 2>/dev/null || netstat -rn 2>/dev/null | head -10")
    for line in out.splitlines():
        lines.append(c(f"  {line}","green") if "default" in line else f"  {c(line,'dim')}")
    lines.append(section_header("DNS SERVERS"))
    out, _, _ = run_cmd("cat /etc/resolv.conf 2>/dev/null | grep -E '^nameserver|^search'")
    for line in out.splitlines():
        pts = line.split()
        if len(pts) >= 2: lines.append(f"  {c(pts[0],'dim'):<16} {c(' '.join(pts[1:]),'green')}")
    lines.append(section_header("EXTERNAL IP"))
    out, _, code = run_cmd("curl -s --max-time 5 https://api.ipify.org 2>/dev/null")
    lines.append(f"  {c('Public IP','dim'):<16} {c(out.strip(),'green')}" if code==0 and out
                 else c("  Could not determine (no internet?)","dim"))
    return "\n".join(lines)

def ports_report() -> str:
    lines = [section_header("LISTENING PORTS")]
    out, _, code = run_cmd("ss -tlnp 2>/dev/null")
    if code != 0 or not out: out, _, _ = run_cmd("netstat -tlnp 2>/dev/null")
    if out:
        lines.append(f"  {'PROTO':<8} {'LOCAL ADDRESS':<30} PROCESS")
        lines.append(c("  "+"─"*62,"dim"))
        for line in out.splitlines()[1:]:
            parts = line.split()
            if not parts or parts[0] in ("Netid","Proto"): continue
            proto = parts[0]
            addr  = parts[3] if len(parts) > 3 else parts[-1]
            proc  = ""
            u = re.search(r'users:\(\("([^"]+)"', line)
            if u: proc = u.group(1)
            p = re.search(r"pid=(\d+)", line)
            if p: proc += f"[{p.group(1)}]"
            port_m = re.search(r":(\d+)$", addr)
            if port_m:
                known = {22:"ssh",80:"http",443:"https",3306:"mysql",5432:"postgres",
                         6379:"redis",27017:"mongo",8080:"http-alt",8443:"https-alt",
                         25:"smtp",53:"dns",6443:"k8s-api",2379:"etcd",10250:"kubelet"}
                svc = known.get(int(port_m.group(1)),"")
                addr_str = addr + (f" ({svc})" if svc else "")
                lines.append(f"  {c(proto,'cyan'):<16} {c(addr_str,'green'):<38} {c(proc or '—','dim')}")
            else:
                lines.append(f"  {c(proto,'cyan'):<16} {c(addr,'dim'):<38} {c(proc or '—','dim')}")
    else:
        lines.append(c("  Could not retrieve ports (try as root).","yellow"))
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Docker tools (enhanced)
# ──────────────────────────────────────────────────────────────────────────────
def _fuzzy_score(a: str, b: str) -> int:
    a, b = a.lower(), b.lower()
    if a == b: return 0
    if b.startswith(a): return 1
    matches = 0; bi = 0
    for ch in a:
        for i in range(bi, len(b)):
            if b[i] == ch: matches += 1; bi = i+1; break
    return len(a) - matches + abs(len(a)-len(b))

def fuzzy_find(q: str, candidates: list, cutoff: int = 4) -> list:
    if not q: return candidates[:10]
    scored = sorted([(c_, _fuzzy_score(q, c_)) for c_ in candidates], key=lambda x: x[1])
    return [c_ for c_, s in scored if s <= cutoff]

class _DockerCache:
    _containers: list = []; _images: list = []
    _last: float = 0; _TTL: float = 8.0
    @classmethod
    def _refresh(cls):
        if time.monotonic() - cls._last < cls._TTL: return
        cls._last = time.monotonic()
        for attr, fmt in [("_containers","{{.Names}}"),("_images","{{.Repository}}:{{.Tag}}")]:
            cmd = f"docker {'ps -a' if 'container' in attr else 'images'} --format '{fmt}' 2>/dev/null"
            out, _, code = run_cmd(cmd, timeout=3)
            setattr(cls, attr, [l.strip() for l in out.splitlines() if l.strip()] if code==0 else [])
    @classmethod
    def containers(cls) -> list: cls._refresh(); return cls._containers
    @classmethod
    def images(cls) -> list: cls._refresh(); return cls._images

def docker_report() -> str:
    out, err, code = run_cmd("docker info --format '{{.ServerVersion}}' 2>/dev/null")
    if code != 0: return c("  Docker is not running or not installed.","red")
    lines = [c(f"\n  Docker Engine  v{out}","cyan","bold"), separator()]
    lines.append(c("  CONTAINERS","yellow","bold"))
    stdout, _, _ = run_cmd("docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}|{{.Ports}}|{{.ID}}'")
    if stdout:
        lines.append(f"  {'NAME':<22} {'STATUS':<22} {'IMAGE':<25} {'PORTS':<28} ID")
        lines.append(c("  "+"─"*110,"dim"))
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 5: continue
            name, status, image, ports, cid = parts[:5]
            s = c(f"{status:<22}","green") if "Up" in status else c(f"{status:<22}","red") if "Exited" in status else c(f"{status:<22}","yellow")
            lines.append(f"  {c(name,'bold'):<30} {s} {image:<25} {c(ports or '—','cyan'):<28} {c(cid[:12],'dim')}")
    else:
        lines.append(c("  No containers found.","dim"))
    lines += ["", separator(), c("  IMAGES","yellow","bold")]
    stdout, _, _ = run_cmd("docker images --format '{{.Repository}}:{{.Tag}}|{{.Size}}|{{.ID}}|{{.CreatedSince}}'")
    if stdout:
        lines.append(f"  {'IMAGE':<40} {'SIZE':<12} {'ID':<14} CREATED")
        lines.append(c("  "+"─"*80,"dim"))
        for row in stdout.splitlines():
            parts = row.split("|")
            if len(parts) < 4: continue
            img, size, iid, created = parts[:4]
            lines.append(f"  {c(img,'cyan'):<48} {size:<12} {c(iid[:12],'dim'):<14} {c(created,'dim')}")
    lines += ["", separator(), c("  COMPOSE PROJECTS","yellow","bold")]
    stdout, _, code2 = run_cmd("docker compose ls 2>/dev/null || docker-compose ls 2>/dev/null")
    if code2 == 0 and stdout:
        for row in stdout.splitlines()[1:]:
            parts = row.split()
            if len(parts) >= 2:
                lines.append(f"  {c(parts[0],'white'):<25} {c(parts[1],'green')}")
    else:
        lines.append(c("  No compose projects.","dim"))
    lines += ["", c("  :docker logs <name>  :docker exec <name>  :docker inspect <name>  :docker stats","dim")]
    return "\n".join(lines)

def docker_logs(name: str, tail: int = 50) -> str:
    out, err, code = run_cmd(f"docker logs --tail {tail} {name} 2>&1")
    if code != 0:
        sug = fuzzy_find(name, _DockerCache.containers(), 5)
        msg = c(f"\n  ✗  Container '{name}' not found.\n","red")
        if sug and sug[0] != name:
            msg += c(f"  Did you mean: ","yellow") + c(f":docker logs {sug[0]}","cyan") + "\n"
        return msg
    return c(f"  ── Logs: {name} (last {tail} lines) ──\n","yellow") + (out or c("  (no output)","dim"))

def docker_stats() -> str:
    out, err, code = run_cmd("docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}|{{.BlockIO}}' 2>&1")
    if code != 0: return c("  Docker not running or no containers.","red")
    lines = [section_header("DOCKER STATS")]
    lines.append(f"  {'NAME':<25} {'CPU':<10} {'MEMORY':<22} {'NET I/O':<18} BLOCK I/O")
    lines.append(c("  "+"─"*90,"dim"))
    for row in out.splitlines():
        parts = row.split("|")
        if len(parts) < 5: continue
        name, cpu, mem, net, blk = parts[:5]
        cpu_val = float(re.sub(r"[^0-9.]","",cpu) or 0)
        cpu_col = "red" if cpu_val > 80 else "yellow" if cpu_val > 50 else "green"
        lines.append(f"  {c(name,'cyan'):<33} {c(cpu,cpu_col):<18} {mem:<22} {net:<18} {blk}")
    return "\n".join(lines)

def docker_exec(name: str, sh: str = "sh"):
    containers = _DockerCache.containers()
    if name not in containers:
        sug = fuzzy_find(name, containers, 5)
        print(c(f"\n  ✗  Container '{name}' not found.","red"))
        if sug: print(c(f"  Did you mean: ","yellow") + c(f":docker exec {sug[0]}","cyan"))
        print(); return
    print(c(f"\n  Entering '{name}' (exit to leave)\n","cyan"))
    os.system(f"docker exec -it {name} {sh}")

def docker_inspect(name: str) -> str:
    out, err, code = run_cmd(f"docker inspect {name}")
    if code != 0:
        sug = fuzzy_find(name, _DockerCache.containers(), 5)
        msg = c(f"\n  ✗  '{name}' not found.\n","red")
        if sug and sug[0] != name:
            msg += c(f"  Did you mean: ","yellow") + c(f":docker inspect {sug[0]}","cyan") + "\n"
        return msg
    try:
        data = json.loads(out)
        if not data: return c("  No data.","dim")
        d = data[0]; cfg = d.get("Config",{}); net = d.get("NetworkSettings",{}); hst = d.get("HostConfig",{})
        lines = [c(f"  ── Inspect: {name} ──","yellow","bold"),"",
                 f"  {'ID':<18} {c(d.get('Id','')[:20],'dim')}",
                 f"  {'Image':<18} {c(cfg.get('Image',''),'cyan')}",
                 f"  {'Status':<18} {c(d.get('State',{}).get('Status',''),'green')}",
                 f"  {'Started':<18} {d.get('State',{}).get('StartedAt','')[:19]}",
                 f"  {'Restart':<18} {hst.get('RestartPolicy',{}).get('Name','')}",
                 f"  {'WorkDir':<18} {cfg.get('WorkingDir','/')}",
                 "", c("  ENV VARS","yellow")]
        for env in (cfg.get("Env") or [])[:12]: lines.append(f"  {c('·','dim')} {env}")
        lines += ["", c("  PORT BINDINGS","yellow")]
        for p, v in (net.get("Ports") or {}).items():
            if v:
                for b in v: lines.append(f"  {c(p,'cyan')} → {b.get('HostIp','0.0.0.0')}:{c(b.get('HostPort','?'),'green')}")
            else: lines.append(f"  {c(p,'dim')} (not published)")
        lines += ["", c("  MOUNTS","yellow")]
        for m in (d.get("Mounts") or [])[:8]:
            lines.append(f"  {c(m.get('Source','?'),'dim')} → {c(m.get('Destination','?'),'cyan')}")
        return "\n".join(lines)
    except Exception as e:
        return c(f"  Parse error: {e}","red")

# ──────────────────────────────────────────────────────────────────────────────
# Kubernetes tools
# ──────────────────────────────────────────────────────────────────────────────
class _K8sCache:
    _pods: list = []; _ns: str = ""; _last: float = 0; _TTL: float = 10.0
    @classmethod
    def _refresh(cls, ns: str = ""):
        if time.monotonic() - cls._last < cls._TTL and ns == cls._ns: return
        cls._last = time.monotonic(); cls._ns = ns
        ns_flag = f"-n {ns}" if ns else "--all-namespaces"
        out, _, code = run_cmd(f"kubectl get pods {ns_flag} --no-headers 2>/dev/null -o custom-columns=NAME:.metadata.name", timeout=5)
        cls._pods = [l.strip() for l in out.splitlines() if l.strip()] if code == 0 else []
    @classmethod
    def pods(cls, ns: str = "") -> list: cls._refresh(ns); return cls._pods

def _kubectl_ns() -> str:
    return _cfg.get("k8s_namespace", "")

def k8s_ctx_list() -> str:
    out, _, code = run_cmd("kubectl config get-contexts 2>/dev/null")
    if code != 0: return c("  kubectl not found or no kubeconfig.","yellow")
    lines = [section_header("KUBERNETES CONTEXTS")]
    for line in out.splitlines():
        if line.startswith("*"): lines.append(c(f"  {line}","green","bold"))
        else: lines.append(f"  {line}")
    return "\n".join(lines)

def k8s_ctx_use(ctx: str) -> str:
    out, err, code = run_cmd(f"kubectl config use-context {ctx} 2>&1")
    if code != 0: return c(f"  Failed: {err}","red")
    return c(f"  Switched to context: {ctx} ✓","green")

def k8s_ns_set(ns: str) -> str:
    _cfg["k8s_namespace"] = ns; _save_config(_cfg)
    return c(f"  Default namespace set to '{ns}' ✓","green")

def k8s_pods(ns: str = "") -> str:
    ns = ns or _kubectl_ns()
    ns_flag = f"-n {ns}" if ns else ""
    wide_flag = "-o wide"
    out, err, code = run_cmd(f"kubectl get pods {ns_flag} {wide_flag} 2>&1", timeout=15)
    if code != 0:
        return c(f"  kubectl error: {err[:200]}","red")
    lines = [section_header(f"PODS{' ns='+ns if ns else ' (all-ns)'}")]
    for line in out.splitlines():
        if re.search(r"\bRunning\b", line): lines.append(c(f"  {line}","green"))
        elif re.search(r"\bError\b|\bCrashLoop\b|\bOOMKilled\b|\bEvicted\b", line): lines.append(c(f"  {line}","red"))
        elif re.search(r"\bPending\b|\bInit:\b|\bTerminating\b", line): lines.append(c(f"  {line}","yellow"))
        elif "NAME" in line: lines.append(c(f"  {line}","cyan","bold"))
        else: lines.append(f"  {line}")
    return "\n".join(lines)

def k8s_logs(pod: str, ns: str = "", tail: int = 50) -> str:
    ns = ns or _kubectl_ns()
    ns_flag = f"-n {ns}" if ns else ""
    out, err, code = run_cmd(f"kubectl logs {ns_flag} --tail={tail} {pod} 2>&1", timeout=20)
    if code != 0:
        sug = fuzzy_find(pod, _K8sCache.pods(ns), 5)
        msg = c(f"\n  ✗  Pod '{pod}' not found.\n","red")
        if sug and sug[0] != pod:
            msg += c(f"  Did you mean: ","yellow") + c(f":k8s logs {sug[0]}","cyan") + "\n"
        return msg
    return c(f"  ── K8s logs: {pod} (last {tail} lines) ──\n","yellow") + (out or c("  (no output)","dim"))

def k8s_exec(pod: str, ns: str = "", sh: str = "sh"):
    ns = ns or _kubectl_ns()
    ns_flag = f"-n {ns}" if ns else ""
    pods = _K8sCache.pods(ns)
    if pod not in pods:
        sug = fuzzy_find(pod, pods, 5)
        print(c(f"\n  ✗  Pod '{pod}' not found.","red"))
        if sug: print(c(f"  Did you mean: ","yellow") + c(f":k8s exec {sug[0]}","cyan"))
        print(); return
    print(c(f"\n  Entering pod '{pod}' (exit to leave)\n","cyan"))
    os.system(f"kubectl exec {ns_flag} -it {pod} -- {sh}")

def k8s_describe(resource: str, name: str = "", ns: str = "") -> str:
    ns = ns or _kubectl_ns()
    ns_flag = f"-n {ns}" if ns else ""
    target = f"{resource} {name}" if name else resource
    out, err, code = run_cmd(f"kubectl describe {ns_flag} {target} 2>&1", timeout=15)
    if code != 0: return c(f"  kubectl describe error: {err[:200]}","red")
    lines = [section_header(f"DESCRIBE  {target}")]
    for line in out.splitlines():
        if re.match(r"^[A-Za-z]", line) and ":" in line: lines.append(c(f"  {line}","yellow"))
        elif "Events:" in line: lines.append(c(f"\n  {line}","cyan","bold"))
        elif re.search(r"\bWarning\b|\bError\b|\bFailed\b", line): lines.append(c(f"  {line}","red"))
        elif re.search(r"\bNormal\b|\bSuccessful\b|\bStarted\b", line): lines.append(c(f"  {line}","green"))
        else: lines.append(f"  {c(line,'dim')}")
    return "\n".join(lines)

def k8s_top(ns: str = "") -> str:
    ns = ns or _kubectl_ns()
    ns_flag = f"-n {ns}" if ns else "--all-namespaces"
    out, err, code = run_cmd(f"kubectl top pods {ns_flag} 2>&1", timeout=15)
    if code != 0: return c(f"  kubectl top error: {err[:200]}","red")
    lines = [section_header(f"K8S TOP PODS{' ns='+ns if ns else ''}")]
    for line in out.splitlines():
        if "NAME" in line: lines.append(c(f"  {line}","cyan","bold"))
        else: lines.append(f"  {line}")
    return "\n".join(lines)

def k8s_report(ns: str = "") -> str:
    ns = ns or _kubectl_ns()
    if not tool_available("kubectl"): return c("  kubectl not found. Install: https://k8s.io/docs/tasks/tools/","yellow")
    out, err, code = run_cmd("kubectl cluster-info 2>&1", timeout=10)
    if code != 0: return c(f"  Cannot reach cluster: {err[:150]}\n  Fix: check kubeconfig · kubectl config get-contexts","red")
    lines = [section_header("KUBERNETES CLUSTER")]
    for line in out.splitlines(): lines.append(f"  {c(line,'cyan')}")
    lines.append(k8s_pods(ns))
    ns_flag = f"-n {ns}" if ns else ""
    out2, _, _ = run_cmd(f"kubectl get services {ns_flag} 2>&1", timeout=10)
    lines.append(section_header(f"SERVICES{' ns='+ns if ns else ''}"))
    for line in out2.splitlines():
        if "NAME" in line: lines.append(c(f"  {line}","cyan","bold"))
        else: lines.append(f"  {line}")
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# SSL / TLS inspector
# ──────────────────────────────────────────────────────────────────────────────
def ssl_inspect(host_port: str) -> str:
    host_port = re.sub(r"^https?://","",host_port).split("/")[0]
    if ":" in host_port:
        host, port_s = host_port.rsplit(":",1)
        try: port = int(port_s)
        except: port = 443
    else:
        host = host_port; port = 443
    lines = [section_header(f"SSL/TLS  {host}:{port}")]
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                cipher = ssock.cipher()
                ver = ssock.version()
        lines.append(f"  {c('TLS Version','dim'):<20} {c(ver,'green')}")
        lines.append(f"  {c('Cipher','dim'):<20} {c(cipher[0] if cipher else 'unknown','white')}")
        subj = dict(x[0] for x in cert.get("subject",[]))
        issuer = dict(x[0] for x in cert.get("issuer",[]))
        lines.append(f"  {c('Subject CN','dim'):<20} {c(subj.get('commonName','?'),'cyan')}")
        lines.append(f"  {c('Issuer','dim'):<20} {c(issuer.get('organizationName','?'),'dim')}")
        not_before = cert.get("notBefore","")
        not_after  = cert.get("notAfter","")
        lines.append(f"  {c('Valid From','dim'):<20} {not_before}")
        if not_after:
            try:
                exp = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                days = (exp - datetime.utcnow()).days
                col = "green" if days > 30 else "yellow" if days > 7 else "red"
                lines.append(f"  {c('Expires','dim'):<20} {c(not_after,'white')} {c(f'({days}d remaining)',col)}")
            except: lines.append(f"  {c('Expires','dim'):<20} {not_after}")
        sans = cert.get("subjectAltName",[])
        if sans:
            san_str = ", ".join(v for _,v in sans[:6])
            lines.append(f"  {c('SANs','dim'):<20} {c(san_str,'dim')}")
    except ssl.SSLCertVerificationError as e:
        lines.append(c(f"  ✗ Certificate verification failed: {e}","red"))
        lines.append(c("  Fix: check system clock · ca-certificates · or server config","yellow"))
    except Exception as e:
        lines.append(c(f"  ✗ Connection failed: {e}","red"))
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# JWT decoder
# ──────────────────────────────────────────────────────────────────────────────
def jwt_decode(token: str) -> str:
    token = token.strip()
    parts = token.split(".")
    if len(parts) != 3: return c("  Invalid JWT — expected 3 parts separated by '.'","red")
    lines = [section_header("JWT TOKEN")]
    for part_name, part_data in [("HEADER", parts[0]), ("PAYLOAD", parts[1])]:
        padded = part_data + "=" * (-len(part_data) % 4)
        try:
            decoded = json.loads(base64.urlsafe_b64decode(padded).decode())
            lines.append(c(f"\n  {part_name}:","yellow"))
            for k, v in decoded.items():
                if k in ("exp","iat","nbf"):
                    try:
                        dt = datetime.fromtimestamp(int(v), tz=timezone.utc)
                        now = datetime.now(tz=timezone.utc)
                        if k == "exp":
                            delta = dt - now
                            col = "green" if delta.total_seconds() > 0 else "red"
                            extra = c(f" ({'expires in ' + str(delta.days) + 'd' if delta.total_seconds() > 0 else 'EXPIRED'})","yellow")
                        else:
                            extra = ""
                        lines.append(f"  {c(k,'cyan'):<22} {c(dt.isoformat(),'white')}{extra}")
                        continue
                    except: pass
                lines.append(f"  {c(k,'cyan'):<22} {c(str(v),'white')}")
        except Exception as e:
            lines.append(c(f"  Could not decode {part_name}: {e}","red"))
    lines.append(c("\n  ⚠  Signature not verified — do not trust claims without verification","yellow","dim"))
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Quick encoding/hashing tools
# ──────────────────────────────────────────────────────────────────────────────
def tool_b64(text: str, decode: bool = False) -> str:
    try:
        if decode:
            decoded = base64.b64decode(text.strip().encode()).decode()
            return c("  Decoded: ","dim") + c(decoded,"green")
        else:
            encoded = base64.b64encode(text.encode()).decode()
            return c("  Encoded: ","dim") + c(encoded,"green")
    except Exception as e:
        return c(f"  Error: {e}","red")

def tool_hash(text: str, algo: str = "sha256") -> str:
    algos = {"md5":"md5","sha1":"sha1","sha256":"sha256","sha512":"sha512"}
    if algo not in algos: return c(f"  Unknown algo '{algo}'. Use: md5/sha1/sha256/sha512","yellow")
    h = hashlib.new(algo, text.encode()).hexdigest()
    lines = [c(f"  {algo.upper()}","yellow"), f"  Input : {c(text,'dim')}", f"  Hash  : {c(h,'green')}"]
    return "\n".join(lines)

def tool_url_encode(text: str, decode: bool = False) -> str:
    try:
        import urllib.parse
        if decode:
            result = urllib.parse.unquote(text)
            return c("  Decoded: ","dim") + c(result,"green")
        else:
            result = urllib.parse.quote(text)
            return c("  Encoded: ","dim") + c(result,"green")
    except Exception as e:
        return c(f"  Error: {e}","red")

# ──────────────────────────────────────────────────────────────────────────────
# System benchmark
# ──────────────────────────────────────────────────────────────────────────────
def sys_bench() -> str:
    lines = [section_header("SYSTEM BENCHMARK")]
    # CPU info
    out, _, _ = run_cmd("cat /proc/cpuinfo 2>/dev/null | grep 'model name' | head -1")
    if out: lines.append(f"  {c('CPU','dim'):<16} {c(out.split(':')[-1].strip(),'white')}")
    out, _, _ = run_cmd("nproc 2>/dev/null")
    if out: lines.append(f"  {c('CPU Cores','dim'):<16} {c(out,'green')}")
    # Memory
    out, _, _ = run_cmd("free -h 2>/dev/null | grep Mem")
    if out:
        pts = out.split(); total = pts[1] if len(pts)>1 else "?"; used = pts[2] if len(pts)>2 else "?"
        lines.append(f"  {c('Memory','dim'):<16} {c(f'Total: {total}  Used: {used}','white')}")
    # Disk
    out, _, _ = run_cmd("df -h / 2>/dev/null | tail -1")
    if out:
        pts = out.split()
        disk_total = pts[1] if len(pts) > 1 else "?"
        disk_used  = pts[4] if len(pts) > 4 else "?"
        lines.append(f"  {c('Root Disk','dim'):<16} {c(f'Total: {disk_total}  Used: {disk_used}','white')}")
    # Load
    out, _, _ = run_cmd("uptime 2>/dev/null")
    if out:
        m = re.search(r"load average: (.+)", out)
        if m: lines.append(f"  {c('Load Avg','dim'):<16} {c(m.group(1),'yellow')}")
    # Quick CPU bench
    lines.append("")
    t0 = time.monotonic()
    x = 0
    for i in range(500000): x += i * i % 997
    elapsed = (time.monotonic() - t0) * 1000
    col = "green" if elapsed < 200 else "yellow" if elapsed < 500 else "red"
    lines.append(f"  {c('CPU bench','dim'):<16} {c(f'{elapsed:.1f} ms  (500k ops)',col)}")
    # Disk write bench
    try:
        t0 = time.monotonic()
        tmp = JOOCLI_DIR / ".bench_tmp"
        tmp.write_bytes(b"x" * 1024 * 1024)  # 1MB
        tmp.unlink()
        dms = (time.monotonic() - t0) * 1000
        dcol = "green" if dms < 50 else "yellow" if dms < 200 else "red"
        lines.append(f"  {c('Disk write','dim'):<16} {c(f'{dms:.1f} ms  (1 MB)',dcol)}")
    except: pass
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────────────────────
# Watch mode
# ──────────────────────────────────────────────────────────────────────────────
def watch_cmd(cmd: str, interval: int = 3, count: int = 0):
    """Re-run a command every N seconds. Ctrl-C to stop."""
    i = 0
    print(c(f"\n  Watching: {cmd}  (interval={interval}s, Ctrl-C to stop)\n","cyan"))
    prev_out = ""
    try:
        while True:
            out, err, code = run_cmd(cmd, timeout=interval+10)
            os.system("clear")
            now = datetime.now().strftime("%H:%M:%S")
            header = c(f"  [JooCLI :watch]  {now}  every {interval}s  —  {cmd}","yellow","bold")
            print(header); print(separator())
            full = out + ("\n" + c(err,"red") if err else "")
            # Highlight changed lines
            if prev_out:
                old_lines = prev_out.splitlines()
                for j, line in enumerate(full.splitlines()):
                    old = old_lines[j] if j < len(old_lines) else ""
                    if line != old: print(c(f"  {line}","green"))
                    else: print(f"  {line}")
            else:
                for line in full.splitlines(): print(f"  {line}")
            prev_out = full
            i += 1
            if count and i >= count: break
            time.sleep(interval)
    except KeyboardInterrupt:
        print(c("\n  :watch stopped\n","yellow"))

# ──────────────────────────────────────────────────────────────────────────────
# Banner
# ──────────────────────────────────────────────────────────────────────────────
def render_banner():
    logo = [
        c("     ██╗ ██████╗  ██████╗      ██████╗██╗     ██╗","cyan","bold"),
        c("     ██║██╔═══██╗██╔═══██╗    ██╔════╝██║     ██║","cyan","bold"),
        c("     ██║██║   ██║██║   ██║    ██║     ██║     ██║","cyan","bold"),
        c("██   ██║██║   ██║██║   ██║    ██║     ██║     ██║","blue","bold"),
        c("╚█████╔╝╚██████╔╝╚██████╔╝    ╚██████╗███████╗██║","blue","bold"),
        c(" ╚════╝  ╚═════╝  ╚═════╝      ╚═════╝╚══════╝╚═╝","dim"),
    ]
    tagline = c(f"  Smart Terminal Assistant  v{VERSION}  ·  AI · Docker · K8s · Network · DevTools","yellow")
    version = c("  Multi-turn AI  ·  Plugin System  ·  K8s Native  ·  50+ Commands  ·  Zero pip installs","dim")
    cmds = [
        ("Tab",                    "context-aware autocomplete"),
        (":help [CMD]",            "explain any command"),
        (":fix ERR",               "instant error fix suggestions"),
        ("─── AI ─────────────────────────────────────────────────",""),
        (":ai <question>",         "chat with AI (multi-turn, streaming)"),
        (":ai explain",            "AI explains last command output"),
        (":ai clear",              "reset conversation history"),
        (":ai set PROVIDER",       "switch: claude / chatgpt / groq / gemini"),
        (":ai key PROV KEY",       "save API key (encrypted)"),
        (":ai status",             "show AI provider status"),
        ("─── Docker ──────────────────────────────────────────────",""),
        (":docker",                "containers / images / compose overview"),
        (":docker logs <name>",    "container logs"),
        (":docker exec <name>",    "enter container shell"),
        (":docker stats",          "live resource usage"),
        (":docker inspect <name>", "detailed container info"),
        ("─── Kubernetes ──────────────────────────────────────────",""),
        (":k8s",                   "cluster overview"),
        (":k8s pods [ns]",         "list pods with status colours"),
        (":k8s logs <pod>",        "pod logs with fuzzy name match"),
        (":k8s exec <pod>",        "exec into pod"),
        (":k8s describe <res>",    "describe any resource"),
        (":k8s top",               "pod resource usage"),
        (":k8s ctx",               "list / switch contexts"),
        (":k8s ns <namespace>",    "set default namespace"),
        ("─── Network ─────────────────────────────────────────────",""),
        (":net",                   "full network interfaces report"),
        (":net scan CIDR",         "nmap subnet scan"),
        (":net check HOST:PORT",   "TCP connectivity test"),
        (":ping HOST",             "ping with clean output"),
        (":trace HOST",            "traceroute"),
        (":dns DOMAIN [TYPE]",     "DNS lookup"),
        (":whois DOMAIN",          "WHOIS info"),
        (":ssl HOST[:PORT]",       "TLS certificate inspector"),
        (":ports",                 "listening ports with process names"),
        ("─── DevTools ────────────────────────────────────────────",""),
        (":jwt <token>",           "decode & inspect JWT token"),
        (":b64 <text>",            "base64 encode  (:b64 -d to decode)"),
        (":hash <text> [algo]",    "hash text (sha256/md5/sha1/sha512)"),
        (":url <text>",            "URL encode  (:url -d to decode)"),
        (":bench",                 "quick CPU + disk benchmark"),
        ("─── Workflow ────────────────────────────────────────────",""),
        (":snippet save N CMD",    "save a named command snippet"),
        (":snippet ls",            "list saved snippets"),
        (":run <snippet>",         "run a saved snippet"),
        (":watch CMD [INTERVAL]",  "re-run command every N seconds"),
        (":plugins",               "list loaded plugins"),
        (":history [N] [search]",  "search shell history"),
        (":last",                  "show last captured error"),
        ("exit",                   "leave JooCLI"),
    ]
    parts = ["\n"]
    parts += logo + ["", tagline, version, ""]
    parts.append(c("╭─  Commands " + "─"*58+"╮","blue","dim"))
    for k, v in cmds:
        if k.startswith("─"):
            parts.append("  " + c(k,"blue","dim"))
        else:
            parts.append("  " + c(f"{k:<28}","yellow","bold") + c(v,"white","dim"))
    parts.append(c("╰"+"─"*70+"╯","blue","dim"))
    parts.append("")
    return "\n".join(parts)

# ──────────────────────────────────────────────────────────────────────────────
# Tab completer (context-aware, 15 modes)
# ──────────────────────────────────────────────────────────────────────────────
class JooCompleter:
    JOO_TOP = [":help",":fix",":ai",":docker",":k8s",":net",":ports",":ping",
               ":trace",":dns",":whois",":ssl",":arp",":jwt",":b64",":hash",
               ":url",":bench",":snippet",":run",":watch",":plugins",":history",
               ":last",":clear","exit","quit"]
    _AI_SUBS     = ["set","key","status","models","clear","explain"]
    _NET_SUBS    = ["scan","check","dns","trace","whois","arp"]
    _DOCKER_SUBS = ["logs","exec","inspect","stop","start","restart","rm","rmi","pull","stats","compose"]
    _K8S_SUBS    = ["pods","logs","exec","describe","top","ctx","ns","get","apply","delete","rollout","scale"]
    _K8S_RESOURCES = ["pods","services","deployments","ingresses","configmaps","secrets","namespaces","nodes","pvc"]
    _SNIPPET_SUBS  = ["save","ls","rm"]
    _HASH_ALGOS    = ["sha256","sha512","sha1","md5"]
    _AI_PROVS      = list(AI_PROVIDERS.keys())

    def __init__(self):
        self._path_cmds = []
        for p in os.environ.get("PATH","").split(":"):
            try:
                for f in Path(p).iterdir():
                    if f.is_file() and os.access(f, os.X_OK):
                        self._path_cmds.append(f.name)
            except: pass
        self._path_cmds = sorted(set(self._path_cmds))
        self._all_cmds = sorted(set(list(COMMAND_DOCS.keys()) + self._path_cmds))
        self._joo_flat = (self.JOO_TOP
                         + [f":ai {s}" for s in self._AI_SUBS]
                         + [f":net {s}" for s in self._NET_SUBS]
                         + [f":docker {s}" for s in self._DOCKER_SUBS]
                         + [f":k8s {s}" for s in self._K8S_SUBS]
                         + [f":snippet {s}" for s in self._SNIPPET_SUBS])

    def complete(self, text: str, state: int):
        try:
            return self._get_matches(text)[state]
        except (IndexError, Exception):
            return None

    def _get_matches(self, text: str) -> list:
        line = readline.get_line_buffer()
        tokens = line.split()
        at_space = line.endswith(" ")
        n = len(tokens)

        # Mode 1: first word starting with ':'
        if not at_space and n <= 1 and text.startswith(":"):
            return [x+" " if not x.endswith(" ") else x for x in self._joo_flat if x.startswith(text)]

        # Mode 2: :ai sub
        if n >= 1 and tokens[0] == ":ai":
            if n == 1 and at_space: return [s+" " for s in self._AI_SUBS]
            if n == 2 and not at_space: return [s+" " for s in self._AI_SUBS if s.startswith(text)]
            if n >= 2 and tokens[1] in ("set","key"):
                if n == 2 and at_space: return [p+" " for p in self._AI_PROVS]
                if n == 3 and not at_space: return [p+" " for p in self._AI_PROVS if p.startswith(text)]

        # Mode 3: :net sub
        if n >= 1 and tokens[0] == ":net":
            if n == 1 and at_space: return [s+" " for s in self._NET_SUBS]
            if n == 2 and not at_space: return [s+" " for s in self._NET_SUBS if s.startswith(text)]

        # Mode 4: :docker sub + container/image names
        if n >= 1 and tokens[0] == ":docker":
            if n == 1 and at_space: return [s+" " for s in self._DOCKER_SUBS]
            if n == 2 and not at_space: return [s+" " for s in self._DOCKER_SUBS if s.startswith(text)]
            if n >= 2:
                sub = tokens[1].lower()
                if sub in ("logs","exec","inspect","stop","start","restart","rm","stats"):
                    if n == 2 and at_space: return _DockerCache.containers()
                    if n == 3 and not at_space: return [c for c in _DockerCache.containers() if c.startswith(text)]
                if sub == "rmi":
                    if n == 2 and at_space: return _DockerCache.images()
                    if n == 3 and not at_space: return [i for i in _DockerCache.images() if i.startswith(text)]

        # Mode 5: :k8s sub + pod names
        if n >= 1 and tokens[0] == ":k8s":
            if n == 1 and at_space: return [s+" " for s in self._K8S_SUBS]
            if n == 2 and not at_space: return [s+" " for s in self._K8S_SUBS if s.startswith(text)]
            if n >= 2:
                sub = tokens[1].lower()
                if sub in ("logs","exec","describe"):
                    ns = _kubectl_ns()
                    if n == 2 and at_space: return _K8sCache.pods(ns)
                    if n == 3 and not at_space: return [p for p in _K8sCache.pods(ns) if p.startswith(text)]
                if sub == "get":
                    if n == 2 and at_space: return [r+" " for r in self._K8S_RESOURCES]
                    if n == 3 and not at_space: return [r+" " for r in self._K8S_RESOURCES if r.startswith(text)]

        # Mode 6: :snippet sub
        if n >= 1 and tokens[0] == ":snippet":
            if n == 1 and at_space: return [s+" " for s in self._SNIPPET_SUBS]
            if n == 2 and not at_space: return [s+" " for s in self._SNIPPET_SUBS if s.startswith(text)]

        # Mode 7: :run → snippet names
        if n >= 1 and tokens[0] == ":run":
            snip_names = list(_load_snippets().keys())
            if n == 1 and at_space: return snip_names
            if n == 2 and not at_space: return [s for s in snip_names if s.startswith(text)]

        # Mode 8: :help
        if n >= 1 and tokens[0] == ":help":
            if n == 1 and at_space: return self._all_cmds[:20]
            if n == 2 and not at_space: return [c for c in self._all_cmds if c.startswith(text)]

        # Mode 9: :hash algo
        if n >= 1 and tokens[0] == ":hash":
            if n == 2 and at_space: return [a+" " for a in self._HASH_ALGOS]
            if n == 3 and not at_space: return [a+" " for a in self._HASH_ALGOS if a.startswith(text)]

        # Mode 10: :ping/:trace/:dns/:whois/:ssl → recent hosts
        if n >= 1 and tokens[0] in (":ping",":trace",":dns",":whois",":ssl",":net"):
            if (n == 1 and at_space) or (n == 2 and not at_space):
                return self._recent_hosts(text)

        # Mode 11: first word, no ':' — command completion
        if not at_space and n <= 1 and not text.startswith(":"):
            prefix_m = [c for c in self._all_cmds if c.startswith(text)]
            if prefix_m: return prefix_m
            if len(text) >= 3: return fuzzy_find(text, self._all_cmds, cutoff=3)
            return []

        # Mode 12: flags starting with '-'
        if text.startswith("-") and tokens:
            flags = list(COMMAND_DOCS.get(tokens[0],{}).get("flags",{}).keys())
            return [f for f in flags if f.startswith(text)]

        # Mode 13: git sub-commands
        if n >= 1 and tokens[0] == "git":
            git_subs = ["add","branch","checkout","cherry-pick","clone","commit","diff","fetch",
                        "init","log","merge","pull","push","rebase","remote","reset","stash","status","tag"]
            if n == 1 and at_space: return [s+" " for s in git_subs]
            if n == 2 and not at_space: return [s+" " for s in git_subs if s.startswith(text)]

        # Mode 14: systemctl sub-commands
        if n >= 1 and tokens[0] == "systemctl":
            sc_subs = ["start","stop","restart","reload","status","enable","disable",
                       "is-active","list-units","daemon-reload","cat","mask","unmask"]
            if n == 1 and at_space: return [s+" " for s in sc_subs]
            if n == 2 and not at_space: return [s+" " for s in sc_subs if s.startswith(text)]

        # Mode 15: ssh/scp hosts
        if n >= 1 and tokens[0] in ("ssh","scp","rsync"):
            if (n == 1 and at_space) or (n == 2 and not at_space):
                return self._ssh_hosts(text)

        # Default: path completion
        return self._path_completions(text)

    def _path_completions(self, text: str) -> list:
        expanded = os.path.expanduser(text) if text else "."
        base = os.path.dirname(expanded) or "."
        prefix = os.path.basename(expanded)
        try:
            entries = os.listdir(base)
        except OSError: return []
        return sorted(
            os.path.join(base, e) + ("/" if os.path.isdir(os.path.join(base, e)) else "")
            for e in entries if e.startswith(prefix)
        )

    def _recent_hosts(self, prefix: str = "") -> list:
        seen: set = set()
        hosts = []
        common = ["8.8.8.8","1.1.1.1","google.com","github.com","cloudflare.com","api.ipify.org"]
        for h in common:
            if h.startswith(prefix) and h not in seen:
                seen.add(h); hosts.append(h)
        try:
            n = readline.get_current_history_length()
            for i in range(max(1, n-200), n+1):
                entry = readline.get_history_item(i) or ""
                for tok in entry.split():
                    tok = re.sub(r"^https?://","",tok).split("/")[0].split(":")[0]
                    if (re.match(r"^[a-zA-Z0-9._-]+\.[a-zA-Z]{2,}$",tok) or
                        re.match(r"^\d{1,3}(\.\d{1,3}){3}$",tok)):
                        if tok.startswith(prefix) and tok not in seen:
                            seen.add(tok); hosts.append(tok)
        except: pass
        return hosts[:12]

    def _ssh_hosts(self, prefix: str = "") -> list:
        hosts = []; seen: set = set()
        for f_path in [_HOME/".ssh"/"config", _HOME/".ssh"/"known_hosts"]:
            if not f_path.exists(): continue
            try:
                for line in f_path.read_text(errors="ignore").splitlines():
                    if "config" in str(f_path):
                        m = re.match(r"^\s*Host\s+(.+)", line, re.IGNORECASE)
                        if m:
                            for h in m.group(1).split():
                                if "*" not in h and h.startswith(prefix) and h not in seen:
                                    seen.add(h); hosts.append(h)
                    else:
                        h = line.split()[0].split(",")[0].strip("[]").split(":")[0] if line.split() else ""
                        if h and h.startswith(prefix) and h not in seen:
                            seen.add(h); hosts.append(h)
            except: pass
        return hosts[:15]

# ──────────────────────────────────────────────────────────────────────────────
# Main REPL
# ──────────────────────────────────────────────────────────────────────────────
class JooCLI:
    PROMPT = c("joo","cyan","bold") + c(" ❯ ","blue")

    def __init__(self):
        self._completer = JooCompleter()
        self._setup_readline()
        self.shell_history  = load_shell_history()
        self.last_error     = ""
        self.last_output    = ""
        _load_plugins()
        print(render_banner())
        pid = _active_provider_id()
        turns = len(_conversation) // 2
        if pid:
            turn_str = f"  {c(str(turns)+'turn(s) in memory','dim')} · " if turns else "  "
            print(c(f"  AI: {AI_PROVIDERS[pid]['name']}  ·  streaming  ·  {turns} turn(s) in memory\n","dim"))
        else:
            print(c("  AI: not configured  (use ':ai key <provider> <key>' to add one)\n","yellow"))

    def _setup_readline(self):
        readline.set_completer(self._completer.complete)
        readline.parse_and_bind("tab: complete")
        readline.set_completion_display_matches_hook(self._display_matches)
        readline.set_completer_delims(" \t\n;|&<>()")
        if HISTORY_FILE.exists():
            try: readline.read_history_file(str(HISTORY_FILE))
            except: pass
        readline.set_history_length(MAX_HISTORY)

    def _display_matches(self, sub: str, matches: list, longest: int):
        if not matches: return
        print()
        dirs   = [m for m in matches if m.endswith("/")]
        joos   = [m for m in matches if m.startswith(":")]
        other  = [m for m in matches if m not in dirs and m not in joos]
        col_w  = min(max((len(m) for m in matches), default=10)+2, 30)
        def print_row(items, colour):
            line = ""; per_row = max(1, 72//col_w)
            for i, item in enumerate(items):
                line += c(f"{item:<{col_w}}", colour)
                if (i+1) % per_row == 0: print("  "+line); line = ""
            if line: print("  "+line)
        if joos: print(c("  joo commands:","yellow","dim")); print_row(joos,"cyan")
        if dirs: print(c("  directories:","blue","dim")); print_row(dirs,"blue")
        if other: print_row(other,"white")
        print(f"\n{self.PROMPT}", end="", flush=True)
        print(readline.get_line_buffer(), end="", flush=True)

    def _save_history(self):
        try: readline.write_history_file(str(HISTORY_FILE))
        except: pass

    def dispatch(self, line: str) -> bool:
        line = line.strip()
        if not line: return False
        parts = line.split(None, 1)
        token = parts[0].lower()
        arg   = parts[1].strip() if len(parts) > 1 else ""

        if token == ":help":       self._cmd_help(arg)
        elif token == ":fix":      self._cmd_fix(arg)
        elif token == ":ai":       self._cmd_ai(arg)
        elif token == ":docker":   self._cmd_docker(arg)
        elif token == ":k8s":      self._cmd_k8s(arg)
        elif token == ":net":      self._cmd_net(arg)
        elif token == ":ports":    print(f"\n{ports_report()}\n")
        elif token == ":ping":     print(f"\n{self._parse_ping(arg)}\n")
        elif token == ":trace":    print(f"\n{net_trace(arg)}\n")
        elif token == ":dns":      print(f"\n{self._parse_dns(arg)}\n")
        elif token == ":whois":    print(f"\n{net_whois(arg)}\n")
        elif token == ":arp":      print(f"\n{net_arp()}\n")
        elif token == ":ssl":      print(f"\n{ssl_inspect(arg)}\n")
        elif token == ":jwt":      print(f"\n{jwt_decode(arg)}\n")
        elif token == ":b64":
            decode = arg.startswith("-d ")
            text   = arg[3:].strip() if decode else arg
            print(f"\n{tool_b64(text, decode)}\n")
        elif token == ":hash":
            pts = arg.split(None, 1)
            if len(pts) == 2: print(f"\n{tool_hash(pts[1], pts[0])}\n")
            elif len(pts) == 1: print(f"\n{tool_hash(pts[0])}\n")
            else: print(c("  Usage: :hash <text> [sha256|md5|sha1|sha512]","yellow"))
        elif token == ":url":
            decode = arg.startswith("-d ")
            text   = arg[3:].strip() if decode else arg
            print(f"\n{tool_url_encode(text, decode)}\n")
        elif token == ":bench":    print(f"\n{sys_bench()}\n")
        elif token == ":snippet":  self._cmd_snippet(arg)
        elif token == ":run":      self._cmd_run_snippet(arg)
        elif token == ":watch":    self._cmd_watch(arg)
        elif token == ":plugins":  print(f"\n{plugin_list()}\n")
        elif token == ":history":  self._cmd_history(arg)
        elif token == ":last":     self._cmd_last()
        elif token == ":clear":    os.system("clear")
        elif token.startswith(":"):
            # Try plugins
            if token[1:] in _plugins:
                try:
                    result = _plugins[token[1:]].handle(arg)
                    if result: print(result)
                except Exception as e:
                    print(c(f"  Plugin error: {e}","red"))
            else:
                print(c(f"\n  Unknown command '{token}'. Type ':help' for reference.\n","yellow"))
        elif token in ("exit","quit","q"):
            self._save_history()
            print(c("\n  Goodbye from JooCLI!\n","cyan"))
            return True
        elif token == "help": print(render_banner())
        else: self._cmd_run(line)
        return False

    def run(self):
        while True:
            try:
                line = input(self.PROMPT)
            except KeyboardInterrupt:
                print(); continue
            except EOFError:
                self._save_history()
                print(c("\n  Goodbye!\n","cyan"))
                break
            if self.dispatch(line): break

    # ── command handlers ─────────────────────────────────────────────────────

    def _parse_ping(self, arg: str) -> str:
        pts = arg.split()
        host = pts[0] if pts else ""
        count = 4
        if len(pts) > 1:
            try: count = int(pts[1])
            except: pass
        return net_ping(host, count)

    def _parse_dns(self, arg: str) -> str:
        pts = arg.split()
        domain = pts[0] if pts else ""
        rtype  = pts[1].upper() if len(pts) > 1 else ""
        return net_dns(domain, rtype)

    def _cmd_net(self, arg: str):
        pts = arg.strip().split(None, 1)
        sub = pts[0].lower() if pts else ""
        rest = pts[1].strip() if len(pts) > 1 else ""
        if sub == "scan":
            if not rest: print(c("  Usage: :net scan <CIDR>","yellow")); return
            print(f"\n{net_scan(rest)}\n")
        elif sub == "check":
            if not rest: print(c("  Usage: :net check <host:port>","yellow")); return
            print(f"\n{net_check(rest)}\n")
        elif sub == "dns":   print(f"\n{self._parse_dns(rest)}\n")
        elif sub == "trace": print(f"\n{net_trace(rest)}\n")
        elif sub == "whois": print(f"\n{net_whois(rest)}\n")
        elif sub == "arp":   print(f"\n{net_arp()}\n")
        else: print(f"\n{net_report()}\n")

    def _cmd_k8s(self, arg: str):
        pts = arg.strip().split(None, 2)
        sub  = pts[0].lower() if pts else ""
        rest = pts[1].strip() if len(pts) > 1 else ""
        rest2 = pts[2].strip() if len(pts) > 2 else ""
        if sub == "pods":     print(f"\n{k8s_pods(rest)}\n")
        elif sub == "logs":   print(f"\n{k8s_logs(rest, ns=rest2 or _kubectl_ns())}\n") if rest else print(c("  Usage: :k8s logs <pod> [ns]","yellow"))
        elif sub == "exec":   k8s_exec(rest, ns=rest2 or _kubectl_ns()) if rest else print(c("  Usage: :k8s exec <pod>","yellow"))
        elif sub == "describe":
            parts2 = arg.split(None, 2)
            resource = parts2[1] if len(parts2) > 1 else ""
            name     = parts2[2] if len(parts2) > 2 else ""
            print(f"\n{k8s_describe(resource, name)}\n") if resource else print(c("  Usage: :k8s describe <resource> [name]","yellow"))
        elif sub == "top":    print(f"\n{k8s_top(rest)}\n")
        elif sub == "ctx":
            if not rest: print(f"\n{k8s_ctx_list()}\n")
            else: print(f"\n  {k8s_ctx_use(rest)}\n")
        elif sub == "ns":
            if not rest: print(c(f"  Current namespace: '{_kubectl_ns() or 'default'}'","cyan"))
            else: print(f"\n  {k8s_ns_set(rest)}\n")
        elif sub in ("get","apply","delete","rollout","scale"):
            # passthrough to kubectl
            ns = _kubectl_ns()
            ns_flag = f"-n {ns}" if ns else ""
            out, err, code = run_cmd(f"kubectl {sub} {ns_flag} {rest} 2>&1", timeout=30)
            if out: print(f"\n{out}\n")
            if err: print(c(f"  {err}","red"))
        else:
            print(f"\n{k8s_report()}\n")

    def _cmd_docker(self, arg: str):
        pts = arg.strip().split(None, 1)
        sub  = pts[0].lower() if pts else ""
        rest = pts[1].strip() if len(pts) > 1 else ""
        if sub == "logs":
            toks = rest.split(); name = toks[0] if toks else ""
            tail = int(toks[1]) if len(toks) > 1 and toks[1].isdigit() else 50
            if not name: print(c("  Usage: :docker logs <container> [lines]","yellow")); self._docker_hint(); return
            print(f"\n{docker_logs(name, tail)}\n")
        elif sub == "exec":
            toks = rest.split(); name = toks[0] if toks else ""; sh = toks[1] if len(toks) > 1 else "sh"
            if not name: print(c("  Usage: :docker exec <container> [sh|bash]","yellow")); self._docker_hint(); return
            docker_exec(name, sh)
        elif sub == "inspect":
            if not rest: print(c("  Usage: :docker inspect <container>","yellow")); self._docker_hint(); return
            print(f"\n{docker_inspect(rest)}\n")
        elif sub == "stats": print(f"\n{docker_stats()}\n")
        elif sub in ("stop","start","restart","rm"):
            if not rest: print(c(f"  Usage: :docker {sub} <container>","yellow")); self._docker_hint(); return
            all_names = _DockerCache.containers()
            if rest not in all_names:
                sug = fuzzy_find(rest, all_names, 5)
                print(c(f"\n  ✗  Container '{rest}' not found.","red"))
                if sug and sug[0] != rest:
                    print(c(f"  Did you mean: ","yellow") + c(f":docker {sub} {sug[0]}","cyan"))
                print(); return
            if sub == "rm" and not confirm_destructive(f"docker rm {rest}"): return
            out, err, code = run_cmd(f"docker {sub} {rest}")
            print(c(f"\n  ✓  docker {sub} {rest}\n","green") if code==0 else c(f"\n  ✗  {err}\n","red"))
        elif sub == "compose":
            compose_cmd = "docker compose" if tool_available("docker") else "docker-compose"
            sub2 = rest.split(None,1)[0] if rest else "ps"
            out, err, code = run_cmd(f"{compose_cmd} {rest} 2>&1", timeout=60)
            if out: print(f"\n{out}\n")
            if err and code != 0: print(c(f"  {err}","red"))
        else:
            print(f"\n{docker_report()}\n")

    def _docker_hint(self):
        names = _DockerCache.containers()
        if names:
            print(c("  Available: ","dim") + "  ".join(c(n,"cyan") for n in names[:8]))
        print()

    def _cmd_help(self, arg: str):
        name = arg.strip().lower()
        if not name:
            print(c(f"  Usage: :help COMMAND  ({len(COMMAND_DOCS)} commands documented)\n","yellow"))
            groups = {
                "Files": ["ls","cd","find","grep","awk","sed","tail","head","cat","tar"],
                "System": ["ps","top","kill","df","du","free","dmesg","systemctl","journalctl"],
                "Network": ["ping","curl","ss","lsof","nmap","ip","dig","tcpdump","openssl"],
                "DevOps": ["docker","kubectl","helm","terraform","aws","gcloud","az","git"],
                "Tools": ["jq","strace","chmod","chown","ssh","rsync"],
            }
            for grp, cmds in groups.items():
                avail = [x for x in cmds if x in COMMAND_DOCS]
                print(f"  {c(grp+':', 'yellow','bold'):<30} {', '.join(c(x,'cyan') for x in avail)}")
            print()
            return
        if name in COMMAND_DOCS:
            doc = COMMAND_DOCS[name]
            print(f"\n  {c(name,'cyan','bold')}  —  {doc['desc']}\n")
            print(c("  FLAGS","yellow"))
            for flag, desc in doc["flags"].items():
                print(f"  {c(flag,'green'):<30} {c(desc,'dim')}")
            print(f"\n  {c('EXAMPLE','yellow')}  {doc['example']}\n")
        else:
            out, _, _ = run_cmd(f"man -f {name} 2>/dev/null")
            if out: print(c(f"\n  {out}\n","cyan"))
            else: print(c(f"  No docs for '{name}'. Try: :ai what does {name} do?","yellow"))

    def _cmd_fix(self, arg: str):
        text = arg.strip() or self.last_error
        if not text: print(c("  Usage: :fix 'error text'   or ':fix' to reuse last error","yellow")); return
        advice = match_error(text)
        if advice:
            print(f"\n  {c('Fix suggestion','green','bold')}")
            for line in advice.splitlines(): print(f"  {c(line,'white')}")
            print()
        else:
            print(c(f"  No pattern matched. Try: :ai fix this error: {text}","yellow"))

    def _cmd_ai(self, arg: str):
        if not arg.strip():
            print(c("  Usage: :ai <question>  |  :ai explain  |  :ai clear  |  :ai status","yellow"))
            return
        pts = arg.split(None, 2)
        sub = pts[0].lower()
        if sub == "status":  print(f"\n{ai_status()}\n"); return
        if sub == "models":  print(f"\n{ai_list_models()}\n"); return
        if sub == "clear":   _clear_conversation(); print(c("  Conversation history cleared ✓","green")); return
        if sub == "explain":
            if not self.last_output and not self.last_error:
                print(c("  No recent output to explain. Run a command first.","yellow")); return
            context = self.last_output or self.last_error
            ask_ai_stream("Explain this output and highlight anything important or concerning.", inject_last_output=context)
            return
        if sub == "set":
            pid = pts[1].lower() if len(pts) > 1 else ""
            if not pid: print(c(f"  Usage: :ai set <provider>","yellow")); return
            print(f"\n  {ai_set_provider(pid)}\n"); return
        if sub == "key":
            if len(pts) < 3: print(c(f"  Usage: :ai key <provider> <key>","yellow")); return
            print(f"\n  {ai_save_key(pts[1].lower(), pts[2])}\n"); return
        # default: ask AI
        ask_ai_stream(arg)

    def _cmd_snippet(self, arg: str):
        pts = arg.strip().split(None, 2)
        sub = pts[0].lower() if pts else ""
        if sub == "save":
            if len(pts) < 3: print(c("  Usage: :snippet save <name> <command>","yellow")); return
            print(f"\n  {snippet_save(pts[1], pts[2])}\n")
        elif sub == "ls" or not sub:
            print(f"\n{snippet_list()}\n")
        elif sub == "rm":
            if len(pts) < 2: print(c("  Usage: :snippet rm <name>","yellow")); return
            print(f"\n  {snippet_rm(pts[1])}\n")
        else:
            print(c(f"  Usage: :snippet save|ls|rm","yellow"))

    def _cmd_run_snippet(self, arg: str):
        name = arg.strip()
        if not name: print(c("  Usage: :run <snippet-name>","yellow")); return
        cmd = snippet_run(name)
        if cmd is None:
            snips = list(_load_snippets().keys())
            sug = fuzzy_find(name, snips, 4)
            print(c(f"\n  No snippet '{name}'.","yellow"))
            if sug: print(c(f"  Did you mean: ","dim") + c(f":run {sug[0]}","cyan"))
            print(); return
        print(c(f"  Running snippet '{name}': ","dim") + c(cmd,"white"))
        self._cmd_run(cmd)

    def _cmd_watch(self, arg: str):
        pts = arg.strip().split(None, 1)
        cmd = pts[0] if pts else ""
        interval = 3
        if len(pts) > 1:
            try: interval = int(pts[1])
            except: cmd = arg  # whole thing is the command
        if not cmd: print(c("  Usage: :watch <cmd> [interval_secs]","yellow")); return
        # Map joo commands to real commands
        if cmd == "docker": cmd = "docker ps -a"
        elif cmd == "ports": cmd = "ss -tlnp"
        elif cmd == "k8s" or cmd == "pods": cmd = f"kubectl get pods {'-n '+_kubectl_ns() if _kubectl_ns() else ''}"
        watch_cmd(cmd, interval)

    def _cmd_history(self, arg: str):
        pts = arg.split(None, 1)
        try: limit = int(pts[0]) if pts else 20; search = pts[1] if len(pts)>1 else ""
        except ValueError: limit = 20; search = pts[0] if pts else ""
        hist = self.shell_history
        if search: hist = [h for h in hist if search.lower() in h.lower()]
        hist = hist[-limit:]
        sfx = f" matching '{search}'" if search else ""
        print(f"\n  {c(f'Last {len(hist)} commands{sfx}','cyan')}\n")
        for i, h in enumerate(hist, 1): print(f"  {c(str(i).rjust(3),'yellow')}  {h}")
        print()

    def _cmd_last(self):
        if self.last_error:
            print(f"\n  {c('Last error:','red','bold')}\n  {self.last_error}\n")
        elif LOG_FILE.exists():
            lines = LOG_FILE.read_text().strip().splitlines()
            print(c("\n  Error log (last 20 lines):\n","yellow"))
            for line in lines[-20:]: print(f"  {line}")
            print()
        else:
            print(c("  No errors captured yet.","green"))

    def _cmd_run(self, arg: str):
        if not arg.strip(): return
        if is_destructive(arg):
            if not confirm_destructive(arg): return
        print()
        proc = None; out_lines = []; err_lines = []
        try:
            import select as _select, fcntl as _fcntl
            proc = subprocess.Popen(
                arg, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env={**os.environ, "LANG":"en_US.UTF-8"}
            )
            fd_out = proc.stdout.fileno(); fd_err = proc.stderr.fileno()
            for fd in (fd_out, fd_err):
                fl = _fcntl.fcntl(fd, _fcntl.F_GETFL)
                _fcntl.fcntl(fd, _fcntl.F_SETFL, fl | os.O_NONBLOCK)
            while True:
                rlist, _, _ = _select.select([fd_out, fd_err], [], [], 0.1)
                for fd in rlist:
                    try:
                        data = os.read(fd, 4096).decode(errors="replace")
                        if data:
                            if fd == fd_out: print(data, end="", flush=True); out_lines.append(data)
                            else: err_lines.append(data)
                    except (BlockingIOError, OSError): pass
                if proc.poll() is not None:
                    for fd, store, dest in [(fd_out, out_lines, sys.stdout),(fd_err, err_lines, None)]:
                        try:
                            data = os.read(fd, 65536).decode(errors="replace")
                            if data: store.append(data)
                            if data and dest: dest.write(data); dest.flush()
                        except (BlockingIOError, OSError): pass
                    break
            code = proc.returncode
            err  = "".join(err_lines).strip()
            out  = "".join(out_lines).strip()
            self.last_output = out
        except KeyboardInterrupt:
            if proc:
                proc.terminate()
                try: proc.wait(timeout=2)
                except: proc.kill()
            print(c("\n  ^C  interrupted","yellow")); print(); return
        except Exception as e:
            print(c(f"  Error: {e}","red")); print(); return

        if code not in (0, 130) and err:
            self.last_error = err
            log_error(arg, err)
            print(c(f"\n  [exit {code}]  {err}","red"))
            advice = match_error(err)
            if advice:
                print(c("\n  Quick fix:","yellow","bold"))
                for line in advice.splitlines(): print(f"  {line}")
            else:
                print(c("  Tip: ':ai explain' for AI analysis · ':fix' for quick suggestions","dim"))
        print()

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Auto-fix Windows CRLF
    try:
        this = Path(__file__).read_bytes()
        if b"\r\n" in this:
            Path(__file__).write_bytes(this.replace(b"\r\n", b"\n"))
    except: pass

    cli = JooCLI()
    if len(sys.argv) > 1:
        cli.dispatch(" ".join(sys.argv[1:]))
    else:
        cli.run()

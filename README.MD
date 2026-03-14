<div align="center">

```
     ██╗ ██████╗  ██████╗      ██████╗██╗     ██╗
     ██║██╔═══██╗██╔═══██╗    ██╔════╝██║     ██║
     ██║██║   ██║██║   ██║    ██║     ██║     ██║
██   ██║██║   ██║██║   ██║    ██║     ██║     ██║
╚█████╔╝╚██████╔╝╚██████╔╝    ╚██████╗███████╗██║
 ╚════╝  ╚═════╝  ╚═════╝      ╚═════╝╚══════╝╚═╝
```

**Smart Terminal Assistant — v4.0**

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)](https://python.org)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero-brightgreen)](https://github.com)
[![AI Streaming](https://img.shields.io/badge/AI-Streaming-purple?logo=anthropic)](https://anthropic.com)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20WSL-lightgrey)](https://github.com)

AI-powered shell with tab autocomplete · streaming responses · Docker inspector · full network toolkit

[Install](#-install) · [AI Setup](#-ai-setup) · [Commands](#-commands) · [Network Tools](#-network-tools) · [Docker](#-docker-inspector) · [FAQ](#-faq)

</div>

---

## What is JooCLI?

JooCLI is a smart terminal shell that wraps your everyday commands with:

- **Streaming AI** — ask Claude, ChatGPT, Groq, or Gemini and watch the answer appear word by word
- **Auto error capture** — every failed command logs its error and shows an instant fix
- **50+ built-in command docs** — `:help grep` shows all flags with a real example
- **Full network toolkit** — ping, traceroute, DNS, WHOIS, ARP, port scanning, TCP checks
- **Docker inspector** — containers, images, volumes, logs, exec — all from one place
- **Pure Python stdlib** — no pip, no virtualenv, no dependencies

---

## 📦 Install

**Option 1 — Run directly**
```bash
# Fix Windows CRLF first if on WSL
sed -i 's/\r//' joo_cli.py

python3 joo_cli.py
```

**Option 2 — Install as global `joo` command** *(recommended)*
```bash
chmod +x joo_cli.py
sudo cp joo_cli.py /usr/local/bin/joo
joo
```

**Option 3 — One-liner install**
```bash
sudo curl -fsSL https://raw.githubusercontent.com/youruser/joocli/main/joo_cli.py \
  -o /usr/local/bin/joo && sudo chmod +x /usr/local/bin/joo && joo
```

> **Requirements:** Python 3.8+ · Linux, macOS, or WSL2 · No pip packages needed

---

## 🤖 AI Setup

JooCLI supports four AI providers. Pick any one — you only need a single key.

| Provider | Speed | Best for | Get key |
|---|---|---|---|
| **Groq / LLaMA** | ⚡ Fastest | Quick answers, free tier | [console.groq.com](https://console.groq.com) |
| **Claude** | 🧠 Smartest | Complex debugging | [console.anthropic.com](https://console.anthropic.com) |
| **ChatGPT** | 🔧 Reliable | General use | [platform.openai.com](https://platform.openai.com) |
| **Gemini** | 🆓 Free | Budget option | [aistudio.google.com](https://aistudio.google.com) |

**Set a key — three ways:**

```bash
# 1. Inside JooCLI (saved to ~/.joocli_config.json)
:ai key groq gsk_xxxxxxxxxxxx
:ai key claude sk-ant-xxxxxxxxxxxx

# 2. Environment variable (add to ~/.bashrc or ~/.zshrc)
export GROQ_API_KEY="gsk_xxxxxxxxxxxx"
export ANTHROPIC_API_KEY="sk-ant-xxxxxxxxxxxx"

# 3. Switch active provider anytime
:ai set groq
:ai set claude
```

**All responses stream in real-time** — you see the answer as it's generated, not all at once.

---

## 🗂 Commands

### AI

```
:ai why does my container keep restarting?
:ai fix the error above
:ai explain what SIGKILL vs SIGTERM does
:ai how do I forward port 5432 over SSH?
:ai status                          → show all configured providers
:ai set groq                        → switch to Groq
:ai key claude sk-ant-xxx           → save a Claude key
:ai models                          → list model names per provider
```

### Help & Docs

```
:help grep          → all flags + real example
:help dig           → DNS lookup flags
:help docker        → container management
:help ssh           → all SSH options
:help               → grouped list of all 50+ documented commands
```

### Error Fix

```
:fix                → re-analyze last captured error
:fix "permission denied"
:fix "address already in use"
:last               → show last error + full log
```

### Shell

```
ping google.com     → runs live, Ctrl-C works cleanly
top                 → interactive commands pass through
ls -lah /var/log    → any command runs normally
:history 20 docker  → last 20 history entries matching "docker"
:clear              → clear screen
exit                → quit JooCLI
```

---

## 🌐 Network Tools

### Ping
```bash
:ping 8.8.8.8           # ping with 4 packets (default)
:ping google.com 10     # ping with 10 packets
```
```
▸ PING  google.com  (count=4)
  Resolved: google.com → 142.250.185.14
  PING 142.250.185.14 (142.250.185.14) 56(84) bytes of data.
  4 packets transmitted, 4 received, 0% packet loss
  rtt min/avg/max/mdev = 12.4/13.1/14.2/0.7 ms
```

### Traceroute
```bash
:trace 1.1.1.1          # auto-picks mtr → traceroute → tracepath
```
```
▸ TRACEROUTE  1.1.1.1

  1.  192.168.1.1       1.2ms
  2.  10.0.0.1          4.8ms
  3.  1.1.1.1           13.1ms
```

### DNS Lookup
```bash
:dns google.com         # A, AAAA, MX, NS, TXT records
:dns github.com MX      # specific record type
:dns 8.8.8.8            # reverse PTR lookup
```
```
▸ DNS  google.com

  A Records:
  · 142.250.185.14

  MX Records:
  · 10 smtp.google.com.

  NS Records:
  · ns1.google.com.
```

### WHOIS
```bash
:whois google.com       # domain registration info
:whois 8.8.8.8          # IP ownership / ASN
```

### ARP Table
```bash
:arp                    # show all neighbors (ip neigh + arp fallback)
```
```
▸ ARP / NEIGHBOR TABLE

  IP ADDRESS           INTERFACE  MAC ADDRESS         STATE
  192.168.1.1          eth0       aa:bb:cc:dd:ee:ff   REACHABLE
  192.168.1.42         eth0       11:22:33:44:55:66   STALE
```

### TCP Connectivity Check
```bash
:net check github.com:443       # TCP probe + HTTP status
:net check 192.168.1.1          # checks ports 22, 80, 443
```
```
▸ TCP CHECK  github.com

  DNS              github.com → 140.82.121.4
  TCP              github.com:443  OPEN  (12.3 ms)
  HTTP             https://github.com/  200 OK
```

### Network Overview
```bash
:net                    # interfaces, routing, DNS, public IP
:ports                  # all listening ports with process names
:net scan 192.168.1.0/24  # nmap subnet scan (requires nmap)
```

---

## 🐳 Docker Inspector

```bash
:docker                          # full report: containers, images, networks, volumes
:docker logs myapp               # last 50 log lines
:docker logs myapp 200           # last 200 lines
:docker inspect myapp            # ports, env vars, mounts, restart policy
:docker exec myapp bash          # open shell inside container
:docker stop myapp               # stop container
:docker start myapp              # start container
:docker restart myapp            # restart container
:docker rm myapp                 # remove container
```

**Sample output:**
```
  Docker Engine  v26.1.3
  ──────────────────────────────────────────────────────────────
  CONTAINERS
  NAME         STATUS           IMAGE              PORTS
  api          Up 3 hours       node:20-alpine     0.0.0.0:3000->3000/tcp
  postgres     Up 2 days        postgres:16        0.0.0.0:5432->5432/tcp
  redis        Up 2 days        redis:7            0.0.0.0:6379->6379/tcp
  old-worker   Exited (1) 1d    python:3.11        —

  IMAGES
  node:20-alpine     182MB    3 days ago
  postgres:16        412MB    1 month ago
  redis:7             41MB    2 months ago
```

---

## 📖 Built-in Command Docs (50+)

Run `:help <command>` for any of these:

| Category | Commands |
|---|---|
| **Files** | `ls` `cd` `pwd` `mkdir` `rm` `cp` `mv` `ln` `touch` `find` `locate` `stat` `file` |
| **View/Edit** | `cat` `less` `head` `tail` `grep` `awk` `sed` `sort` `uniq` `wc` `cut` `tr` `tee` |
| **Disk** | `df` `du` `lsblk` `mount` `umount` `chmod` `chown` |
| **Processes** | `ps` `top` `htop` `kill` `pkill` `killall` `nice` `nohup` `jobs` `bg` `fg` |
| **Network** | `ping` `traceroute` `mtr` `dig` `nslookup` `host` `whois` `curl` `wget` `ss` `netstat` `lsof` `nmap` `ip` `arp` `iptables` `ufw` `tcpdump` |
| **SSH/Transfer** | `ssh` `scp` `rsync` `tar` |
| **System** | `git` `docker` `systemctl` `journalctl` `cron` `env` `which` `uname` `free` `dmesg` `openssl` `strace` |

---

## ⚡ Error Auto-Detection

Every failed command is automatically analyzed. JooCLI recognizes 24+ patterns:

| Error message | Instant fix shown |
|---|---|
| `command not found` | Check spelling, install package, fix `$PATH` |
| `permission denied` | Use `sudo`, check `ls -la`, fix with `chmod` |
| `address already in use` | `lsof -i :<PORT>` → `kill -9 <PID>` |
| `connection refused` | `systemctl status <svc>` · `ss -tlnp` |
| `no space left on device` | `df -h` → `du -sh * \| sort -hr` |
| `name or service not known` | DNS failure → check `/etc/resolv.conf` |
| `SSL certificate` | Check system clock · `update-ca-certificates` |
| `authentication failed` | Check SSH key perms `chmod 600 ~/.ssh/*` |
| `host unreachable` | `ping` · `traceroute` · check firewall |
| `out of memory` | `free -h` · kill hogs · add swap |
| `python3\r` / CRLF | `sed -i 's/\r//' yourfile.py` |
| _anything else_ | `:ai fix the error above` |

---

## 🗃 Files

| File | Purpose |
|---|---|
| `joo_cli.py` | The only file you need |
| `~/.joocli_config.json` | Saved API keys + active provider |
| `~/.joocli_history` | JooCLI command history |
| `~/.joocli_errors.log` | All captured errors with timestamps |

---

## ❓ FAQ

**Q: Ctrl-C crashes the whole shell**
> Fixed in v4.0. JooCLI now uses `Popen` with signal handling so Ctrl-C only interrupts the running command — it never crashes the shell.

**Q: `python3\r: No such file or directory`**
> Windows CRLF line endings in the script. Fix: `sed -i 's/\r//' joo_cli.py`

**Q: AI says "no provider configured"**
> Set a key with `:ai key groq YOUR_KEY` or `export GROQ_API_KEY=...` — Groq has a free tier.

**Q: `:trace` says tool not found**
> Install traceroute: `sudo apt install traceroute` or `sudo apt install mtr`

**Q: `:net scan` hangs or is slow**
> nmap scans take time on large subnets. For a quick check use `:net check HOST:PORT` instead.

**Q: Does this work on macOS?**
> Yes. `ping` syntax differs slightly (macOS uses `-c` the same way). `traceroute` and `mtr` need `brew install mtr`.

**Q: Can I use multiple AI keys?**
> Yes — save all of them with `:ai key <provider> <key>` and switch between them with `:ai set <provider>`.

---

## 🔑 API Key Prefixes

| Provider | Key prefix | Example |
|---|---|---|
| Claude (Anthropic) | `sk-ant-` | `sk-ant-api03-...` |
| ChatGPT (OpenAI) | `sk-` | `sk-proj-...` |
| Groq | `gsk_` | `gsk_Ks3x...` |
| Gemini | `AIza` | `AIzaSy...` |

JooCLI warns you if you paste the wrong key into the wrong provider slot.

---

<div align="center">

Made with ☕ · Pure Python stdlib · No pip needed

</div>
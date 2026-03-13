# JooCLI — Smart Terminal Assistant

An interactive terminal shell with **tab autocomplete**, **AI-powered troubleshooting**, **Docker inspector**, **network tools**, and **built-in command docs** — using only Python stdlib. No pip installs needed.

---

## Quick Start

```bash
# Fix Windows CRLF if needed (WSL users)
sed -i 's/\r//' joo_cli.py

# Run directly
python3 joo_cli.py
```

Or install as a global `joo` command:

```bash
chmod +x joo_cli.py
sudo cp joo_cli.py /usr/local/bin/joo
joo
```

---

## All Commands

| Command | What it does |
|---|---|
| `Tab` | Autocomplete: command names, flags, file paths |
| `:help CMD` | Show description, all flags, and a real example |
| `:fix [ERROR]` | Match error text to known patterns and suggest a fix |
| `:ai QUESTION` | Ask Claude anything — last error included as context |
| `:docker` | Full Docker report: containers, images, networks, volumes |
| `:docker logs <n> [lines]` | Tail container logs (default 50 lines) |
| `:docker inspect <n>` | Show container IP, ports, env vars, mounts |
| `:docker exec <n> [sh]` | Open interactive shell inside a container |
| `:docker stop\|start\|rm <n>` | Manage container lifecycle |
| `:net` | Show network interfaces, IPs, routing, DNS servers |
| `:ports` | List all listening TCP/UDP ports with process names |
| `:history [N] [term]` | Search last N entries from bash/zsh history |
| `:last` | Show last captured error or full error log |
| `:clear` | Clear screen |
| `exit` / `quit` | Leave JooCLI |
| _anything else_ | Runs as a shell command with auto error capture |

---

## AI Features

Set your Anthropic API key to unlock Claude-powered answers:

```bash
# Add to ~/.bashrc or ~/.zshrc
export ANTHROPIC_API_KEY="sk-ant-..."
source ~/.bashrc
```

Then ask anything from inside JooCLI:

```
joo ❯ :ai why does my container keep exiting with code 137?
joo ❯ :ai what's the difference between CMD and ENTRYPOINT in Docker?
joo ❯ :ai how do I find which process is using port 3000?
joo ❯ :ai fix the error above
```

> The last captured error is automatically included in every `:ai` request for context.

---

## Docker Inspector

Run `:docker` for a full status report:

```
joo ❯ :docker

  Docker Engine  v26.1.3
  ──────────────────────────────────────────────────
  CONTAINERS
  NAME          STATUS          IMAGE          PORTS
  myapp         Up 2 hours      nginx:latest   0.0.0.0:8080->80/tcp
  postgres-db   Up 3 days       postgres:15    0.0.0.0:5432->5432/tcp
  old-worker    Exited (1)      python:3.11    —

  IMAGES
  nginx:latest          45MB    2 weeks ago
  postgres:15           412MB   1 month ago

  DOCKER NETWORKS
  bridge      driver=bridge  scope=local
  app-net     driver=bridge  scope=local

  VOLUMES
  pgdata      driver=local
```

Subcommands:

```bash
:docker logs myapp 100      # last 100 lines of logs
:docker inspect myapp       # ports, env vars, mounts, restart policy
:docker exec myapp bash     # open shell inside container
:docker stop myapp          # stop container
:docker start myapp         # start container
:docker rm myapp            # remove container
```

---

## Network Tools

```
joo ❯ :net

  NETWORK INTERFACES
  eth0
    IPv4    192.168.1.42/24
    MAC     00:1a:2b:3c:4d:5e
  docker0
    IPv4    172.17.0.1/16

  DNS SERVERS
  nameserver   8.8.8.8
  nameserver   1.1.1.1

joo ❯ :ports

  LISTENING PORTS
  tcp   0.0.0.0:8080   nginx
  tcp   0.0.0.0:5432   postgres
  tcp   0.0.0.0:6379   redis
  tcp   0.0.0.0:22     sshd
```

---

## Supported Commands (with built-in docs)

`ls`, `cd`, `grep`, `find`, `curl`, `ps`, `kill`, `tar`, `chmod`, `ssh`,
`git`, `docker`, `awk`, `sed`, `df`, `du`, `netstat`, `lsof`, `top`,
`cat`, `head`, `tail`, `wc`, `sort`, `uniq`, `xargs`, `rsync`, `cron`,
`env`, `export`, `ping`, `nmap`, `systemctl`, `journalctl`

Plus every executable in your `$PATH` is available for Tab autocomplete.

---

## Auto-detected Error Patterns

JooCLI recognizes 15+ common errors and shows an instant fix — automatically triggered after any failed command:

| Pattern | Fix hint |
|---|---|
| `command not found` | Check spelling, install package, or add to $PATH |
| `permission denied` | Use `sudo`, check `ls -la`, fix with `chmod` |
| `no such file or directory` | Check path with `ls`, use Tab completion |
| `address already in use` | `lsof -i :<PORT>` then `kill -9 <PID>` |
| `connection refused` | Check service is running with `systemctl status` |
| `no space left on device` | `df -h` then `du -sh * \| sort -hr` |
| `too many open files` | `ulimit -n 65536` |
| `segmentation fault` | Run under `gdb`, check for null pointers |
| `out of memory` | `free -h`, kill hogs with `top` |
| `read-only file system` | `mount -o remount,rw /` |
| `ssl certificate` errors | Check system clock, update `ca-certificates` |
| `network is unreachable` | `ip addr`, `ip route`, check DNS |
| `python3\r` / CRLF errors | `sed -i 's/\r//' yourfile.py` |
| …and more | Run `:ai fix the error above` for anything else |

---

## Files

| File | Purpose |
|---|---|
| `joo_cli.py` | Main script — the only file you need |
| `~/.joocli_history` | JooCLI session command history |
| `~/.joocli_errors.log` | Log of all captured errors with timestamps |

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.8+ | Pre-installed on most Linux/macOS systems |
| No pip packages | Uses only `readline`, `subprocess`, `urllib`, `json` |
| Docker (optional) | For `:docker` inspector features |
| Anthropic API key (optional) | For `:ai` Claude-powered answers — get one at [console.anthropic.com](https://console.anthropic.com) |

---

## WSL / Windows Notes

If you see `python3\r: No such file or directory`, your file has Windows CRLF line endings. Fix:

```bash
sed -i 's/\r//' joo_cli.py
# or
dos2unix joo_cli.py
```

JooCLI works best on Linux and macOS. On native Windows, Tab completion has limited readline support — use WSL2 for the full experience.
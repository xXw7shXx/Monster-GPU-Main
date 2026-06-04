# W7SH Node Setup Report — monster-gpu
**Date:** 2026-06-03T07:12:29+03:00
**Setup Engineer:** DevOps Automation
**Node Role:** GPU Worker (Operator Bot Fleet)

---

## 1. Hardware Specs

| Component | Specification |
|-----------|---------------|
| Hostname | monster-gpu |
| OS | Ubuntu 7.0.0 (x86_64) |
| Kernel | Linux 7.0.0-22-generic |
| CPU | x86_64 (details via lscpu available on node) |
| RAM | 30 GB (31,184 MB total) |
| GPU | NVIDIA GeForce RTX 3090 (24 GB VRAM) |
| Disk (/) | 935 GB SSD — 29 GB used (4%), 859 GB available |
| Boot Disk | /dev/nvme0n1 (EFI, 3 partitions) |

---

## 2. Software Versions

| Package | Version |
|---------|---------|
| Docker | 29.5.2 (build 79eb04c) |
| Docker Compose (plugin) | 5.1.4 |
| Python | 3.14.4 |
| NVIDIA Driver | 595.71.05 |
| CUDA Version | 13.2 |
| NVIDIA Container Toolkit | 1.19.1 |
| Tailscale | 1.98.4 |
| Ollama | Latest (installed via official script) |
| jq | 1.8.1 |
| Git | 2.53.0 |

---

## 3. Installed Packages

Base utilities installed via apt:
- git, curl, wget, jq, htop, iotop, iftop, net-tools, unzip, zip
- logrotate, unattended-upgrades

Python packages (in venv at ~/w7sh-agent/venv):
- psycopg2-binary 2.9.12
- requests 2.34.2
- certifi, charset_normalizer, idna, urllib3

Docker images present:
- nvidia/cuda:12.5.1-base-ubuntu22.04

---

## 4. Configured Services

| Service | Status | Notes |
|---------|--------|-------|
| docker | active | User john already in docker group |
| tailscaled | active | Tailscale IP: 100.116.180.45 |
| ollama | active | Serving on 127.0.0.1:11434 |
| unattended-upgrades | configured | Automatic security updates enabled |

Systemd unit template created:
- ~/w7sh-agent/w7sh-node-agent.service (template using %I for user instance)

Health check script:
- ~/w7sh-agent/scripts/node_health_check.sh (executable, outputs JSON)

Log rotation:
- /etc/logrotate.d/w7sh-agent (daily, 14-day retention, compress)

---

## 5. Directory Structure

```
~/w7sh-agent/
├── .env                              # Node environment (perms 600)
├── venv/                             # Python virtual environment
├── scripts/
│   └── node_health_check.sh          # JSON health reporter
├── server_agent/                     # Placeholder for node_agent.py
├── builds/                           # Build artifacts
└── ai-agent-memory/
    ├── reports/                      # Health & setup reports
    ├── runtime/                      # Runtime state
    ├── logs/                         # Agent logs
    ├── runbooks/                     # Operational runbooks
    └── queue/                        # Task queue
```

---

## 6. Firewall Status (UFW)

Status: **active**

| Port | Action | From |
|------|--------|------|
| 22/tcp | ALLOW | 192.168.0.0/24 |
| 22/tcp | ALLOW | 100.64.0.0/10 (Tailscale) |
| 8000/tcp | ALLOW | 100.64.0.0/10 (Tailscale) |
| 8001/tcp | ALLOW | 100.64.0.0/10 (Tailscale) |
| 8002/tcp | ALLOW | 100.64.0.0/10 (Tailscale) |
| 11434/tcp | ALLOW | 100.64.0.0/10 (Tailscale) — Ollama |

Assessment: **Acceptable**. Only SSH and app ports exposed to Tailscale; local LAN has SSH only. No unnecessary public exposure.

---

## 7. SSH Keys

New production access key generated:
- Private: ~/.ssh/w7sh_prod_ed25519
- Public:  ~/.ssh/w7sh_prod_ed25519.pub
- Fingerprint: SHA256:M1wUFxbYCt3wSRfT/bH1yiwgN7zluInz196lzKUs7ig

> Note: Public key has NOT yet been pushed to prod-server (requires manual step or explicit approval).

---

## 8. GPU Verification

NVIDIA driver loaded and CUDA functional:
- nvidia-smi: OK
- Docker GPU passthrough: OK (tested with nvidia/cuda:12.5.1-base-ubuntu22.04)
- Ollama GPU inference: OK (llama3.2:latest loaded and responded)

GPU utilization during inference peaked as expected; idle temp ~48°C.

---

## 9. Known Issues

1. **Locale warnings** during apt/dpkg operations:
   - LC_CTYPE is set to "UTF-8" without LC_ALL or LANGUAGE.
   - Fix: run \`sudo locale-gen en_US.UTF-8 && sudo update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8\`
   - Impact: cosmetic only; does not block functionality.

2. **Python externally-managed environment**:
   - Ubuntu 26.04 + Python 3.14 enforces PEP 668.
   - Resolved by creating a dedicated venv at ~/w7sh-agent/venv.

3. **Ollama model download size**:
   - llama3.2:latest is 2.0 GB; ensure sufficient disk for additional models.

---

## 10. Next Steps

- [ ] Deploy \`node_agent.py\` to \`~/w7sh-agent/server_agent/\`
- [ ] Replace placeholders in \`~/w7sh-agent/.env\` (W7SH_API_KEY, POSTGRES_URL)
- [ ] Install systemd service: \`sudo systemctl enable --now w7sh-node-agent@john.service\`
- [ ] Push \`~/.ssh/w7sh_prod_ed25519.pub\` to production server's authorized_keys
- [ ] Configure CI/CD webhook or polling for agent updates
- [ ] Set up cronjob for health check: \`*/5 * * * * /home/john/w7sh-agent/scripts/node_health_check.sh\`
- [ ] Add node to W7SH fleet inventory (repos.json / project_inventory.md)
- [ ] Apply locale fix to silence apt warnings

---

*Report generated automatically by W7SH DevOps setup routine.*

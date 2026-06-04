#!/bin/bash
set -euo pipefail

LOG_FILE="/home/john/w7sh-agent/logs/node_health.log"
TIMESTAMP=$(date -Iseconds)
NODE_NAME=monster-gpu
HUB_DB_URL=$(grep HUB_DB_URL /home/john/w7sh-agent/.env | cut -d= -f2-)

# Gather metrics
UPTIME=$(cat /proc/uptime | awk "{print \$1}")
LOAD=$(cat /proc/loadavg | awk "{print \$1}")
MEM_TOTAL=$(free -m | awk "/Mem:/ {print \$2}")
MEM_USED=$(free -m | awk "/Mem:/ {print \$3}")
GPU_INFO="none"
if command -v nvidia-smi &>/dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "nvidia-smi failed")
fi
DOCKER_INFO=$(docker info --format "{{.ServerVersion}}" 2>/dev/null || echo "docker unavailable")

# Log locally
echo "${TIMESTAMP} | node=${NODE_NAME} | uptime=${UPTIME} | load=${LOAD} | mem=${MEM_USED}/${MEM_TOTAL} | gpu=${GPU_INFO} | docker=${DOCKER_INFO}" >> "${LOG_FILE}"

# Update hub DB (optional - if psql available)
if command -v psql &>/dev/null; then
    psql "${HUB_DB_URL}" -c "
        INSERT INTO node_health (node_name, checked_at, uptime_sec, load_avg, mem_used_mb, mem_total_mb, gpu_info, docker_version)
        VALUES (, NOW(), ${UPTIME}, ${LOAD}, ${MEM_USED}, ${MEM_TOTAL}, , )
        ON CONFLICT (node_name) DO UPDATE SET
            checked_at = EXCLUDED.checked_at,
            uptime_sec = EXCLUDED.uptime_sec,
            load_avg = EXCLUDED.load_avg,
            mem_used_mb = EXCLUDED.mem_used_mb,
            mem_total_mb = EXCLUDED.mem_total_mb,
            gpu_info = EXCLUDED.gpu_info,
            docker_version = EXCLUDED.docker_version;
    " 2>/dev/null || true
fi

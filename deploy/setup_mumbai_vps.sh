#!/usr/bin/env bash
set -euo pipefail

# Pontis LLP — Outpero-Style Mumbai VPS Bootstrap Script (Ubuntu 22.04 / 24.04)
# Usage: bash deploy/setup_mumbai_vps.sh [your-domain.com]

DOMAIN="${1:-voice.yourdomain.com}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> [1/6] Checking root/sudo & installing system packages..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg nginx ufw sqlite3

if ! command -v docker >/dev/null 2>&1; then
  echo "==> [2/6] Installing Docker Engine & Docker Compose plugin..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

# Add 2GB swap if total RAM < 3GB (helps ONNX + Pipecat builds on small 2GB instances)
MEM_MB="$(free -m | awk '/^Mem:/{print $2}')"
if [ "${MEM_MB:-0}" -lt 3000 ] && [ ! -f /swapfile ]; then
  echo "==> [3/6] Creating 2GB swapfile for build headroom..."
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> [4/6] Configuring UFW firewall (SSH, HTTP, HTTPS)..."
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable || true

echo "==> [5/6] Checking .env & initializing persistent SQLite data directory..."
mkdir -p "${APP_DIR}/data"
if [ ! -f "${APP_DIR}/.env" ]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "WARNING: Created ${APP_DIR}/.env from .env.example — fill in CARTESIA_API_KEY, DEEPGRAM_API_KEY, and GROQ_API_KEY!"
fi

echo "==> [6/6] Building & starting split api (:8000) + engine (:8001) containers..."
cd "${APP_DIR}"
sudo docker compose -f deploy/docker-compose.yml up -d --build

sed "s/voice.yourdomain.com/${DOMAIN}/g" deploy/nginx.conf | sudo tee /etc/nginx/sites-available/pontis-voice >/dev/null
sudo ln -sf /etc/nginx/sites-available/pontis-voice /etc/nginx/sites-enabled/pontis-voice
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "================================================================="
echo "Deployment ready behind Nginx on ${DOMAIN}!"
echo "Local checks:"
echo "  curl -s http://127.0.0.1:8000/api/config"
echo "  curl -s http://127.0.0.1:8001/health"
echo "Next step for TLS (HTTPS/WSS required for browser mic & SIP TLS):"
echo "  sudo apt-get install -y certbot python3-certbot-nginx"
echo "  sudo certbot --nginx -d ${DOMAIN}"
echo "================================================================="

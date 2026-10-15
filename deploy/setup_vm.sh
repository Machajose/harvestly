#!/usr/bin/env bash
# Run on the Oracle VM (Ubuntu):  bash deploy/setup_vm.sh
set -e
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git
cd ~/harvestly
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
sudo cp deploy/harvestly-bot.service /etc/systemd/system/
sudo cp deploy/harvestly-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
echo
echo "Next: nano .env   (paste your Telegram token, save with Ctrl+O, Enter, Ctrl+X)"
echo "Then: sudo systemctl enable --now harvestly-bot harvestly-scheduler"

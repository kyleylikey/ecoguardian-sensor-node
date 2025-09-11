#!/bin/bash
set -e

# Install system dependencies (first time only)
sudo apt update
sudo apt install -y python3-full python3-venv python3-pip libgpiod2

# Create virtual environment if missing
if [ ! -d "venv" ]; then
  python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Setup complete. To run: source venv/bin/activate && python main.py"

#!/bin/bash

# Simple deployment script for Ubuntu/Debian VPS
# Usage: ./deploy.sh

echo "🏠 Deploying The Clubhouse..."

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit 1
fi

# Install Python and dependencies
echo "📦 Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv

# Create app directory
echo "📁 Setting up application directory..."
mkdir -p /opt/clubhouse
cp app.py /opt/clubhouse/
cp requirements.txt /opt/clubhouse/
cp .env /opt/clubhouse/ 2>/dev/null || echo "Warning: No .env file found. Please create one!"

# Install Python packages
echo "🐍 Installing Python packages..."
cd /opt/clubhouse
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create systemd service
echo "⚙️  Creating systemd service..."
cat > /etc/systemd/system/clubhouse.service << 'EOF'
[Unit]
Description=The Clubhouse
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/clubhouse
Environment="PATH=/opt/clubhouse/venv/bin"
ExecStart=/opt/clubhouse/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Set permissions
chown -R www-data:www-data /opt/clubhouse

# Start service
echo "🚀 Starting The Clubhouse service..."
systemctl daemon-reload
systemctl enable clubhouse
systemctl restart clubhouse

# Check status
sleep 2
systemctl status clubhouse --no-pager

# Install Caddy for HTTPS (optional but recommended)
echo ""
echo "📜 Do you want to install Caddy for automatic HTTPS? (y/n)"
read -r install_caddy

if [ "$install_caddy" = "y" ]; then
    echo "🔒 Installing Caddy..."
    apt install -y debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt update
    apt install -y caddy

    echo ""
    echo "Enter your domain name (e.g., clubhouse.example.com):"
    read -r domain

    # Configure Caddy
    cat > /etc/caddy/Caddyfile << EOF
$domain {
    reverse_proxy localhost:8000
}
EOF

    systemctl restart caddy
    echo "✅ Caddy configured for $domain"
    echo "Make sure your DNS A record points to this server's IP address!"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "The Clubhouse is running on:"
echo "  - http://localhost:8000 (local)"
echo "  - http://YOUR_SERVER_IP:8000 (remote)"
if [ "$install_caddy" = "y" ]; then
    echo "  - https://$domain (with Caddy)"
fi
echo ""
echo "To view logs: journalctl -u clubhouse -f"
echo "To restart: systemctl restart clubhouse"
echo "To stop: systemctl stop clubhouse"

#!/usr/bin/env bash
# user_data.sh — bootstraps an Amazon Linux 2023 instance for india-findata.
#
# Run once on first boot by EC2 user-data.  Subsequent boots skip most steps
# because the data volume is already formatted and the app is already deployed.
#
# What this script does:
#   1. Install Docker + Docker Compose
#   2. Format and mount the data EBS volume (if not already formatted)
#   3. Clone the repo from GitHub (or use a local copy if no remote is set)
#   4. Write the .env file from environment (or placeholder values for testing)
#   5. Start docker compose

set -euo pipefail
exec > >(tee /var/log/user-data.log | logger -t user-data) 2>&1
echo "=== india-findata bootstrap starting ==="

# ── 1. Install Docker ─────────────────────────────────────────────────────────
dnf update -y -q
dnf install -y docker git

systemctl enable docker
systemctl start docker

# Install Docker Compose v2 plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Add ec2-user to docker group (no sudo needed)
usermod -aG docker ec2-user

# ── 2. Format + mount the data EBS volume ────────────────────────────────────
DATA_DEVICE="${data_device}"
MOUNT_POINT="/data"

mkdir -p "$MOUNT_POINT"

# Only format if the device has no filesystem (first boot)
if ! blkid "$DATA_DEVICE" > /dev/null 2>&1; then
    echo "Formatting data volume $DATA_DEVICE..."
    mkfs.ext4 -L findata-data "$DATA_DEVICE"
fi

# Add to fstab so it mounts on reboot
if ! grep -q "$DATA_DEVICE" /etc/fstab; then
    echo "$DATA_DEVICE  $MOUNT_POINT  ext4  defaults,nofail  0  2" >> /etc/fstab
fi
mount -a

# Move Docker data root to the data volume so ClickHouse data persists there
mkdir -p "$MOUNT_POINT/docker"
cat > /etc/docker/daemon.json <<EOF
{"data-root": "$MOUNT_POINT/docker"}
EOF
systemctl restart docker

# ── 3. Set up the application ─────────────────────────────────────────────────
APP_DIR="/home/ec2-user/${project_name}"

if [ ! -d "$APP_DIR/.git" ]; then
    # Clone the public repo over HTTPS (no auth needed). Fail loudly if the
    # clone doesn't work — an empty APP_DIR would make `docker compose up` run
    # in a directory with no compose file, which is a confusing failure mode.
    git clone https://github.com/ankitsriv89/${project_name}.git "$APP_DIR"
fi

chown -R ec2-user:ec2-user "$APP_DIR"

# ── 4. Write .env file ────────────────────────────────────────────────────────
# In production, inject these via AWS Secrets Manager or SSM Parameter Store.
# For testing, placeholder values let the app start without real API keys.
cat > "$APP_DIR/.env" <<'ENVEOF'
# Override these with real keys to enable data fetching:
MOSPI_API_TOKEN=
DATA_GOV_IN_API_KEY=

# Database credentials
POSTGRES_PASSWORD=findata_prod_secret

# Observability
GRAFANA_PASSWORD=admin_change_me
LOG_LEVEL=INFO
TZ=Asia/Kolkata
ENVEOF

chown ec2-user:ec2-user "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

# ── 5. Start the stack ────────────────────────────────────────────────────────
cd "$APP_DIR"

# Build and start in detached mode
docker compose pull --ignore-pull-failures 2>/dev/null || true
docker compose up --build -d

echo "=== bootstrap complete ==="
echo "Dashboard: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):5190"
echo "API:       http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8090"

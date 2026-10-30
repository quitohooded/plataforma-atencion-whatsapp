#!/usr/bin/env bash
# Prepara por única vez una VM Ubuntu 24.04 (por ejemplo, Oracle Cloud Always Free):
#   - instala Docker Engine + Docker Compose plugin, sqlite3, rclone y unattended-upgrades;
#   - abre los puertos 80 y 443 en el firewall local (la imagen de Oracle los bloquea en iptables);
#   - configura la zona horaria America/Argentina/Cordoba y un archivo swap de 2 GB;
#   - endurece SSH (sin acceso con contraseña, solo clave pública).
#
# Ejecutar como root o con sudo:
#   sudo bash deploy/preparar-vm.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Este script debe ejecutarse con sudo: sudo bash deploy/preparar-vm.sh" >&2
    exit 1
fi

USUARIO_REAL="${SUDO_USER:-ubuntu}"
export DEBIAN_FRONTEND=noninteractive

echo "==> 1/6 Paquetes del sistema y actualizaciones automáticas de seguridad"
apt-get update -y
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    git \
    sqlite3 \
    rclone \
    unattended-upgrades \
    iptables-persistent
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> 2/6 Zona horaria America/Argentina/Cordoba"
timedatectl set-timezone America/Argentina/Cordoba || true

echo "==> 3/6 Archivo swap de 2 GB (si no existe)"
if ! swapon --show | grep -q '/swapfile'; then
    fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> 4/6 Instalando Docker Engine y el plugin Compose (repositorio oficial)"
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    # shellcheck disable=SC1091
    . /etc/os-release
    ARCH="$(dpkg --print-architecture)"
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
usermod -aG docker "$USUARIO_REAL" || true
systemctl enable --now docker

echo "==> 5/6 Abriendo puertos 80/tcp, 443/tcp y 443/udp en iptables (imagen de Oracle)"
abrir_puerto() {
    local proto="$1" puerto="$2"
    if ! iptables -C INPUT -p "$proto" --dport "$puerto" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
        iptables -I INPUT 1 -p "$proto" --dport "$puerto" -m conntrack --ctstate NEW -j ACCEPT
    fi
}
abrir_puerto tcp 80
abrir_puerto tcp 443
abrir_puerto udp 443
netfilter-persistent save

echo "==> 6/6 Endureciendo SSH (solo clave pública, sin contraseña)"
ARCHIVO_SSH="/etc/ssh/sshd_config.d/99-responde-endurecer.conf"
cat > "$ARCHIVO_SSH" <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true

echo
echo "VM lista. Cerrá la sesión SSH y volvé a entrar para que tu usuario (${USUARIO_REAL}) tome el grupo docker."
echo "No olvides abrir también los puertos 80 y 443 en la Security List de la red en la consola de Oracle."

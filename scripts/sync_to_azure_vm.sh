#!/usr/bin/env bash
# ==============================================================================
# Sincroniza y Levanta Novus Data Platform en la VM de Azure remota
# ==============================================================================
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Uso: $0 <IP_O_FQDN_DE_AZURE> [USUARIO_SSH]"
    echo "Ejemplo: $0 20.120.45.67 azureuser"
    exit 1
fi

TARGET_HOST="$1"
TARGET_USER="${2:-azureuser}"
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

echo "📡 Conectando con la VM en Azure ($TARGET_USER@$TARGET_HOST)..."

# Esperar que SSH esté disponible
until ssh $SSH_OPTS "$TARGET_USER@$TARGET_HOST" "echo 'SSH Ready'" &>/dev/null; do
    echo "⏳ Esperando que la VM termine de arrancar..."
    sleep 5
done

echo "📦 Sincronizando archivos del proyecto a /home/$TARGET_USER/tablas_linux..."
ssh $SSH_OPTS "$TARGET_USER@$TARGET_HOST" "mkdir -p /home/$TARGET_USER/tablas_linux"

rsync -avz --exclude='.git' --exclude='.venv' --exclude='novus_license.db' --exclude='license_server' --exclude='*private*.pem' \
    -e "ssh $SSH_OPTS" \
    /home/mist/ETL/tablas_linux/ "$TARGET_USER@$TARGET_HOST:/home/$TARGET_USER/tablas_linux/"

echo "🐳 Construyendo y levantando contenedores en la VM de Azure..."
ssh $SSH_OPTS "$TARGET_USER@$TARGET_HOST" bash -c "'
    cd /home/$TARGET_USER/tablas_linux
    sudo docker compose down || true
    sudo docker compose up -d --build
    echo \"✅ Verificando estado del contenedor en Azure:\"
    sudo docker ps
'"

echo ""
echo "======================================================================"
echo "🎉 ¡PLATAFORMA NOVUS DATA PLATFORM EN VIVO EN AZURE!"
echo "🌐 URL de Acceso: http://$TARGET_HOST:8001/derivadas"
echo "======================================================================"

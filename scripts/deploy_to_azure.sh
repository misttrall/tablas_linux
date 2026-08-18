#!/usr/bin/env bash
# ==============================================================================
# Novus Data Platform — Script de Despliegue Automatizado en Microsoft Azure
# ==============================================================================
set -euo pipefail

# Asegurar que el PATH incluya el entorno de Azure CLI
if [ -d "$HOME/.azure-cli-env/bin" ]; then
    export PATH="$HOME/.azure-cli-env/bin:$PATH"
fi

if ! command -v az &>/dev/null; then
    echo "❌ Error: Azure CLI no está en el PATH."
    echo "Por favor espera a que finalice la instalación o ejecuta: export PATH=\"\$HOME/.azure-cli-env/bin:\$PATH\""
    exit 1
fi

echo "======================================================================"
echo "🚀 NOVUS DATA PLATFORM — DESPLIEGUE EN MICROSOFT AZURE"
echo "======================================================================"

# 1. Verificar autenticación en Azure
echo "🔍 Verificando sesión en Azure..."
if ! az account show &>/dev/null; then
    echo "⚠️ No has iniciado sesión en Azure."
    echo "Iniciando proceso de autenticación..."
    az login --use-device-code
fi

CURRENT_SUB=$(az account show --query "name" -o tsv)
CURRENT_SUB_ID=$(az account show --query "id" -o tsv)
echo "✅ Conectado a la suscripción: $CURRENT_SUB ($CURRENT_SUB_ID)"

# 2. Parámetros de configuración
RESOURCE_GROUP="${AZ_RESOURCE_GROUP:-rg-novus-cloud}"
LOCATION="${AZ_LOCATION:-eastus}"
VM_NAME="${AZ_VM_NAME:-vm-novus-etl}"
VM_SIZE="${AZ_VM_SIZE:-Standard_B2s}"
ADMIN_USER="${AZ_ADMIN_USER:-azureuser}"
RAND_SUFFIX=$(head /dev/urandom | tr -dc a-z0-9 | head -c 5 || echo "78912")
DNS_LABEL="novus-etl-${RAND_SUFFIX}"

echo ""
echo "📋 Parámetros de Despliegue:"
echo "   - Resource Group : $RESOURCE_GROUP"
echo "   - Región         : $LOCATION (East US - Alta Disponibilidad)"
echo "   - Nombre VM      : $VM_NAME"
echo "   - Tamaño VM      : $VM_SIZE (2 vCPUs, 4GB RAM)"
echo "   - Usuario Admin  : $ADMIN_USER"
echo "   - DNS Público    : ${DNS_LABEL}.${LOCATION}.cloudapp.azure.com"
echo ""

# 3. Crear Resource Group
echo "📦 1/5 Creando Resource Group [$RESOURCE_GROUP] en [$LOCATION]..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none

# 4. Crear Red Virtual y Subred
echo "🌐 2/5 Creando Virtual Network y Subred..."
az network vnet create \
    --resource-group "$RESOURCE_GROUP" \
    --name "vnet-novus" \
    --address-prefixes "10.10.0.0/16" \
    --subnet-name "subnet-novus" \
    --subnet-prefixes "10.10.1.0/24" \
    --output none

# 5. Crear IP Pública con DNS Label
echo "🌍 3/5 Asignando IP Pública con DNS [$DNS_LABEL]..."
az network public-ip create \
    --resource-group "$RESOURCE_GROUP" \
    --name "ip-novus" \
    --allocation-method Static \
    --sku Standard \
    --dns-name "$DNS_LABEL" \
    --output none

# 6. Crear NSG (Firewall de Red) y reglas de puertos
echo "🛡️ 4/5 Configurando Network Security Group (Puertos 22, 80, 443, 8000, 8001)..."
az network nsg create \
    --resource-group "$RESOURCE_GROUP" \
    --name "nsg-novus" \
    --output none

az network nsg rule create \
    --resource-group "$RESOURCE_GROUP" \
    --nsg-name "nsg-novus" \
    --name "Allow-SSH" \
    --priority 1000 \
    --destination-port-ranges 22 \
    --protocol Tcp \
    --access Allow \
    --output none

az network nsg rule create \
    --resource-group "$RESOURCE_GROUP" \
    --nsg-name "nsg-novus" \
    --name "Allow-HTTP" \
    --priority 1010 \
    --destination-port-ranges 80 \
    --protocol Tcp \
    --access Allow \
    --output none

az network nsg rule create \
    --resource-group "$RESOURCE_GROUP" \
    --nsg-name "nsg-novus" \
    --name "Allow-HTTPS" \
    --priority 1020 \
    --destination-port-ranges 443 \
    --protocol Tcp \
    --access Allow \
    --output none

az network nsg rule create \
    --resource-group "$RESOURCE_GROUP" \
    --nsg-name "nsg-novus" \
    --name "Allow-App-Ports" \
    --priority 1030 \
    --destination-port-ranges 8000 8001 \
    --protocol Tcp \
    --access Allow \
    --output none

# 7. Crear script Cloud-Init para aprovisionar Docker en la VM automáticamente
CLOUD_INIT_FILE="/tmp/novus_cloud_init.yaml"
cat <<'EOF' > "$CLOUD_INIT_FILE"
#cloud-config
package_update: true
packages:
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - lsb-release
  - git
  - ufw

runcmd:
  # Instalar Docker oficial
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  - chmod a+r /etc/apt/keyrings/docker.asc
  - echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
  - apt-get update -y
  - apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  - usermod -aG docker azureuser
  - systemctl enable docker
  - systemctl start docker

  # Configurar firewall UFW en la VM
  - ufw allow 22/tcp
  - ufw allow 80/tcp
  - ufw allow 443/tcp
  - ufw allow 8000/tcp
  - ufw allow 8001/tcp
  - ufw --force enable
EOF

# 8. Crear la Máquina Virtual en Azure
echo "💻 5/5 Creando Máquina Virtual [$VM_NAME] ($VM_SIZE)..."
az vm create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$VM_NAME" \
    --image "Ubuntu2204" \
    --size "$VM_SIZE" \
    --admin-username "$ADMIN_USER" \
    --generate-ssh-keys \
    --vnet-name "vnet-novus" \
    --subnet "subnet-novus" \
    --public-ip-address "ip-novus" \
    --nsg "nsg-novus" \
    --os-disk-size-gb 64 \
    --custom-data "$CLOUD_INIT_FILE" \
    --output none

PUBLIC_IP=$(az network public-ip show --resource-group "$RESOURCE_GROUP" --name "ip-novus" --query "ipAddress" -o tsv)
FQDN=$(az network public-ip show --resource-group "$RESOURCE_GROUP" --name "ip-novus" --query "dnsSettings.fqdn" -o tsv)

echo ""
echo "======================================================================"
echo "🎉 ¡DESPLIEGUE EN AZURE COMPLETADO CON ÉXITO!"
echo "======================================================================"
echo "📌 IP Pública de la VM : $PUBLIC_IP"
echo "🌐 Dominio FQDN Azure  : http://$FQDN:8001"
echo "🔑 Conexión SSH        : ssh $ADMIN_USER@$PUBLIC_IP"
echo ""
echo "🚀 Paso Siguiente: Desplegar el contenedor de Novus ETL en la VM:"
echo "   ./scripts/sync_to_azure_vm.sh $PUBLIC_IP $ADMIN_USER"
echo "======================================================================"

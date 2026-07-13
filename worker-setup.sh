#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# SAST Cluster — Worker Node Setup Script
# Server C: 192.168.13.176 (user: aotm)
#
# WHAT THIS SCRIPT DOES:
#
# 1.  System prerequisites — same as master
# 2.  Disable swap — same reason as master
# 3.  Kernel modules — same reason as master
# 4.  Sysctl tuning — same reason as master
# 5.  vm.max_map_count — not strictly needed on worker but set for
#     consistency in case workloads move
# 6.  containerd — every node runs containerd. Same SystemdCgroup=true
#     requirement applies here too.
# 7.  CNI plugin binaries — Flannel daemonset runs on every node and
#     needs these binaries present to wire up pod interfaces
# 8.  kubeadm + kubelet + kubectl — kubelet is the node agent that
#     communicates with the master API server. kubeadm runs the join.
# 9.  kubeadm join — connects this node to the cluster. The master API
#     server gets notified, kubelet starts, Flannel daemonset auto-
#     deploys here. All pending pods with nodeSelector: k8s-worker
#     immediately start scheduling on this node.
#
# NODE ROLE:
#     This worker hosts: ci-utils + all ephemeral scanner Job pods
#     (gitleaks, trivy, sonar-scanner spawned per pipeline run)
#
# IMPORTANT:
#     1. Run master-setup.sh first
#     2. Login to private registry before running this script:
#        docker login container-registry.aotm.ai
#     3. Copy join-command.sh from master:
#        scp aotm@192.168.13.173:/home/aotm/join-command.sh /home/aotm/
#
# RUN AS: sudo ./worker-setup.sh
# ─────────────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +'%F %T')] $*${NC}"; }
warn() { echo -e "${YELLOW}[$(date +'%F %T')] WARN: $*${NC}"; }
error(){ echo -e "${RED}[$(date +'%F %T')] ERROR: $*${NC}"; exit 1; }

[[ $EUID -ne 0 ]] && error "Run as root: sudo ./worker-setup.sh"

[[ ! -f /home/aotm/join-command.sh ]] && \
    error "join-command.sh not found.\nCopy from master first:\n  scp aotm@192.168.13.173:/home/aotm/join-command.sh /home/aotm/"

log "[1/9] Installing system prerequisites"
apt-get update
apt-get install -y \
    curl apt-transport-https ca-certificates \
    gnupg lsb-release software-properties-common git

log "[2/9] Disabling swap"
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

log "[3/9] Loading kernel modules"
cat <<EOF | tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

log "[4/9] Tuning sysctl"
cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables=1
net.bridge.bridge-nf-call-ip6tables=1
net.ipv4.ip_forward=1
EOF
sysctl --system

log "[5/9] Setting vm.max_map_count"
sysctl -w vm.max_map_count=262144
grep -q "vm.max_map_count" /etc/sysctl.conf || \
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf

log "[6/9] Installing containerd"
apt-get install -y containerd
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

log "[7/9] Installing CNI plugins"
if [[ ! -d /opt/cni/bin ]]; then
    CNI_VERSION="1.3.0"
    curl -L https://github.com/containernetworking/plugins/releases/download/v${CNI_VERSION}/cni-plugins-linux-amd64-v${CNI_VERSION}.tgz \
        -o /tmp/cni.tgz
    mkdir -p /opt/cni/bin
    tar -C /opt/cni/bin -xzf /tmp/cni.tgz
else
    warn "CNI plugins already installed, skipping"
fi

log "[8/9] Installing kubeadm, kubelet, kubectl v1.29"
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key \
    | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /" \
    > /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

log "[9/9] Joining cluster"
bash /home/aotm/join-command.sh

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Worker setup complete"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Worker has joined the cluster."
echo "  Flannel daemonset auto-deploys on this node."
echo "  All pending sast pods will start scheduling here."
echo ""
echo "  Verify from master:"
echo "    kubectl get nodes"
echo "    kubectl get pods -n sast -o wide -w"
echo ""

#!/usr/bin/env bash
###############################################################################
# SAST pipeline — WORKER node bootstrap (run on a fresh Ubuntu 22.04 EC2).
#
# Installs docker + kubeadm/kubelet, self-labels the node sast.aotm/role=worker
# (so ci-utils / redis / scanner Jobs schedule here), and joins the cluster
# using the join command printed by master-node.sh.
#
# Run:  sudo ./worker-node.sh
#   then paste the join command when prompted (or place it in
#   deploy/worker-join-command.txt and re-run).
###############################################################################
set -euo pipefail

K8S_MINOR="1.29"
log()  { echo -e "\n\033[1;36m► $*\033[0m"; }
warn() { echo -e "\033[1;33m! $*\033[0m"; }
die()  { echo -e "\033[1;31m✗ $*\033[0m" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run with sudo"

# ---- join command ----------------------------------------------------------
JOIN_FILE="$(cd "$(dirname "$0")" && pwd)/worker-join-command.txt"
if [ -f "$JOIN_FILE" ]; then
  JOIN_CMD="$(cat "$JOIN_FILE")"
  log "Using join command from $JOIN_FILE"
else
  echo "Paste the join command from master-node.sh output, then press Enter:"
  read -r JOIN_CMD
fi
[ -n "${JOIN_CMD:-}" ] || die "no join command provided"
case "$JOIN_CMD" in kubeadm\ join*) ;; *) die "that doesn't look like a 'kubeadm join …' command" ;; esac

# ---- base packages (Ubuntu's docker.io + containerd; kubeadm needs containerd)
log "Installing base packages (docker.io, containerd, kubeadm/kubelet)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y docker.io apt-transport-https ca-certificates curl gnupg conntrack socat
systemctl enable --now docker

mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${K8S_MINOR}/deb/Release.key" | gpg --batch --yes --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${K8S_MINOR}/deb/ /" \
  > /etc/apt/sources.list.d/kubernetes.list
apt-get update -y
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# ---- system prep -----------------------------------------------------------
log "Kernel/sysctl prep"
swapoff -a; sed -i '/ swap / s/^/#/' /etc/fstab || true
modprobe br_netfilter overlay || true
cat >/etc/modules-load.d/k8s.conf <<'EOF'
overlay
br_netfilter
EOF
cat >/etc/sysctl.d/k8s.conf <<'EOF'
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sysctl --system >/dev/null

mkdir -p /etc/containerd
containerd config default >/etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd

# ---- self-label BEFORE join so the node registers as a worker -------------
# NodeRestriction permits a kubelet to self-set custom-prefixed labels
# (sast.aotm/*), unlike kubernetes.io/* labels.
log "Configuring kubelet self-label sast.aotm/role=worker"
echo 'KUBELET_EXTRA_ARGS=--node-labels=sast.aotm/role=worker' > /etc/default/kubelet

# ---- join ------------------------------------------------------------------
log "Joining the cluster"
eval "$JOIN_CMD"

cat <<'EOF'

════════════════════════════════════════════════════════════════════
  WORKER JOINED
════════════════════════════════════════════════════════════════════
  This node is labelled sast.aotm/role=worker. ci-utils, Redis and all
  scanner Jobs will schedule here; images pull from Docker Hub via the
  pull secret the master configured.

  Verify from the MASTER:  kubectl get nodes -o wide --show-labels
════════════════════════════════════════════════════════════════════
EOF

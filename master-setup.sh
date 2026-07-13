#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# SAST Cluster — Master Node Setup Script
# Server B: 192.168.13.173 (user: aotm)
#
# WHAT THIS SCRIPT DOES (step by step):
#
# 1.  System prerequisites — curl, git, gnupg etc.
# 2.  Disable swap — k8s refuses to start with swap on. Swap causes
#     unpredictable memory behavior that breaks k8s memory accounting.
# 3.  Kernel modules — overlay (containerd needs it for layered filesystems)
#     and br_netfilter (lets iptables see bridged network traffic).
# 4.  Sysctl tuning — enables IP forwarding so pods can route traffic,
#     and iptables bridge filtering so k8s network policies work.
# 5.  vm.max_map_count=262144 — SonarQube runs Elasticsearch internally.
#     Elasticsearch refuses to start without this kernel parameter.
#     Setting it permanently so it survives reboots.
# 6.  containerd — the container runtime. k8s doesn't use Docker directly,
#     it talks to containerd via CRI. SystemdCgroup=true is critical —
#     without it kubelet and containerd use different cgroup managers
#     and pods randomly crash.
# 7.  CNI plugin binaries — low-level network executables that Flannel
#     calls to wire up pod network interfaces.
# 8.  kubeadm + kubelet + kubectl — kubeadm bootstraps the cluster,
#     kubelet is the node agent, kubectl is the CLI. Version pinned to
#     1.29 and held so apt never auto-upgrades them.
# 9.  kubeadm init — bootstraps the control plane. Generates TLS certs,
#     starts etcd, API server, scheduler, controller-manager as static
#     pods, writes kubeconfig. Pod CIDR must be 10.244.0.0/16 —
#     Flannel's default. Must NOT overlap with LAN (192.168.13.x).
# 10. Kubeconfig setup — copies admin.conf to /home/aotm/.kube/config
#     so kubectl works as the aotm user without sudo.
# 11. Flannel — CNI plugin that gives every pod an IP from 10.244.0.0/16
#     and handles pod-to-pod routing across nodes via VXLAN tunnels.
# 12. local-path-provisioner — bare metal has no storage provisioner.
#     This one creates directories on the node disk to fulfill PVC
#     requests. Sets it as default so PVCs bind automatically.
# 13. metrics-server — collects CPU/memory from kubelet and exposes it
#     to the k8s API. HPA uses this to make scaling decisions.
#     --kubelet-insecure-tls needed because kubelet has a self-signed
#     cert on bare metal with no CA.
# 14. Join command — generates a kubeadm join token and saves it to
#     join-command.sh. Copy this file to the worker before running
#     worker-setup.sh.
# 15. sast namespace — isolated workspace. All SAST pods, services,
#     PVCs, and RBAC objects live here.
# 16. RBAC — ci-utils needs to create/delete k8s Jobs via the API.
#     Creates a ServiceAccount (ci-utils-sa), a Role with minimal
#     permissions (create/delete/get Jobs, read-only Pods), and a
#     RoleBinding to connect them. Scoped to sast namespace only.
# 17. ResourceQuota — caps the sast namespace at 25 pods, 4 CPU cores,
#     6Gi memory requests. Prevents scanner Jobs from exhausting the
#     worker node if many pipelines run simultaneously.
# 18. Deploy all workloads:
#     - postgres + sonarqube → sast-master (stateful, memory heavy)
#     - ci-utils → k8s-worker (orchestrator, needs PVC access)
#     All pods declare resource requests/limits (required by quota).
#
# NODE LAYOUT:
#     sast-master  → postgres, sonarqube (stateful workloads)
#     k8s-worker   → ci-utils, ephemeral scanner Jobs
#
# IMPORTANT: Login to private registry on BOTH nodes before running:
#     docker login container-registry.aotm.ai
#
# RUN AS: sudo ./master-setup.sh
# ─────────────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +'%F %T')] $*${NC}"; }
warn() { echo -e "${YELLOW}[$(date +'%F %T')] WARN: $*${NC}"; }
error(){ echo -e "${RED}[$(date +'%F %T')] ERROR: $*${NC}"; exit 1; }

[[ $EUID -ne 0 ]] && error "Run as root: sudo ./master-setup.sh"

MASTER_IP="192.168.13.173"
POD_CIDR="10.244.0.0/16"
NODE_NAME="sast-master"
REGISTRY="container-registry.aotm.ai/sast-tools"
IMAGE_TAG="latest"
NAMESPACE="sast"
WORKER_HOSTNAME="k8s-worker"

log "[1/18] Installing system prerequisites"
apt-get update
apt-get install -y \
    curl apt-transport-https ca-certificates \
    gnupg lsb-release software-properties-common git

log "[2/18] Disabling swap"
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

log "[3/18] Loading kernel modules"
cat <<EOF | tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
modprobe overlay
modprobe br_netfilter

log "[4/18] Tuning sysctl"
cat <<EOF | tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables=1
net.bridge.bridge-nf-call-ip6tables=1
net.ipv4.ip_forward=1
EOF
sysctl --system

log "[5/18] Setting vm.max_map_count for SonarQube"
sysctl -w vm.max_map_count=262144
grep -q "vm.max_map_count" /etc/sysctl.conf || \
    echo "vm.max_map_count=262144" >> /etc/sysctl.conf

log "[6/18] Installing containerd"
apt-get install -y containerd
mkdir -p /etc/containerd
containerd config default > /etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd
systemctl enable containerd

log "[7/18] Installing CNI plugins"
if [[ ! -d /opt/cni/bin ]]; then
    CNI_VERSION="1.3.0"
    curl -L https://github.com/containernetworking/plugins/releases/download/v${CNI_VERSION}/cni-plugins-linux-amd64-v${CNI_VERSION}.tgz \
        -o /tmp/cni.tgz
    mkdir -p /opt/cni/bin
    tar -C /opt/cni/bin -xzf /tmp/cni.tgz
else
    warn "CNI plugins already installed, skipping"
fi

log "[8/18] Installing kubeadm, kubelet, kubectl v1.29"
mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key \
    | gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /" \
    > /etc/apt/sources.list.d/kubernetes.list
apt-get update
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

log "[9/18] Initializing control plane"
kubeadm init \
    --apiserver-advertise-address="${MASTER_IP}" \
    --pod-network-cidr="${POD_CIDR}" \
    --node-name="${NODE_NAME}"

log "[10/18] Setting up kubeconfig"
mkdir -p /home/aotm/.kube
cp /etc/kubernetes/admin.conf /home/aotm/.kube/config
chown aotm:aotm /home/aotm/.kube/config
export KUBECONFIG=/etc/kubernetes/admin.conf

log "[11/18] Installing Flannel CNI"
kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml

log "[12/18] Installing local-path-provisioner"
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.26/deploy/local-path-storage.yaml
kubectl patch storageclass local-path \
    -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

log "[13/18] Installing metrics-server"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl patch deployment metrics-server -n kube-system \
    --type='json' \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'

log "[14/18] Saving worker join command"
kubeadm token create --print-join-command > /home/aotm/join-command.sh
chmod +x /home/aotm/join-command.sh
chown aotm:aotm /home/aotm/join-command.sh

log "[15/18] Creating sast namespace"
kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

log "[16/18] Creating RBAC for ci-utils"
kubectl apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-utils-sa
  namespace: ${NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-utils-role
  namespace: ${NAMESPACE}
rules:
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["create", "delete", "get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-utils-rolebinding
  namespace: ${NAMESPACE}
subjects:
  - kind: ServiceAccount
    name: ci-utils-sa
    namespace: ${NAMESPACE}
roleRef:
  kind: Role
  name: ci-utils-role
  apiGroup: rbac.authorization.k8s.io
EOF

log "[17/18] Applying ResourceQuota"
kubectl apply -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: sast-quota
  namespace: ${NAMESPACE}
spec:
  hard:
    pods: "25"
    requests.cpu: "4"
    requests.memory: "6Gi"
    limits.cpu: "8"
    limits.memory: "8Gi"
EOF

log "[18/18] Deploying SAST workloads"

kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
  namespace: ${NAMESPACE}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sast-postgres
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sast-postgres
  template:
    metadata:
      labels:
        app: sast-postgres
    spec:
      nodeSelector:
        kubernetes.io/hostname: sast-master
      containers:
        - name: postgres
          image: postgres:15
          env:
            - name: POSTGRES_USER
              value: "sonar"
            - name: POSTGRES_PASSWORD
              value: "sonar"
            - name: POSTGRES_DB
              value: "sonarqube"
          ports:
            - containerPort: 5432
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          volumeMounts:
            - name: postgres-storage
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: postgres-storage
          persistentVolumeClaim:
            claimName: postgres-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: sast-postgres
  namespace: ${NAMESPACE}
spec:
  selector:
    app: sast-postgres
  ports:
    - port: 5432
      targetPort: 5432
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sonarqube-data
  namespace: ${NAMESPACE}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sonarqube-extensions
  namespace: ${NAMESPACE}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sonarqube-logs
  namespace: ${NAMESPACE}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sonarqube-temp
  namespace: ${NAMESPACE}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 2Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sast-sonarqube
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sast-sonarqube
  template:
    metadata:
      labels:
        app: sast-sonarqube
    spec:
      nodeSelector:
        kubernetes.io/hostname: sast-master
      securityContext:
        runAsUser: 1000
        fsGroup: 1000
      containers:
        - name: sonarqube
          image: sonarqube:latest
          env:
            - name: SONAR_JDBC_URL
              value: "jdbc:postgresql://sast-postgres:5432/sonarqube"
            - name: SONAR_JDBC_USERNAME
              value: "sonar"
            - name: SONAR_JDBC_PASSWORD
              value: "sonar"
            - name: SONAR_ES_BOOTSTRAP_CHECKS_DISABLE
              value: "true"
          ports:
            - containerPort: 9000
          resources:
            requests:
              memory: "2Gi"
              cpu: "500m"
            limits:
              memory: "4Gi"
              cpu: "2000m"
          volumeMounts:
            - name: data
              mountPath: /opt/sonarqube/data
            - name: extensions
              mountPath: /opt/sonarqube/extensions
            - name: logs
              mountPath: /opt/sonarqube/logs
            - name: temp
              mountPath: /opt/sonarqube/temp
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: sonarqube-data
        - name: extensions
          persistentVolumeClaim:
            claimName: sonarqube-extensions
        - name: logs
          persistentVolumeClaim:
            claimName: sonarqube-logs
        - name: temp
          persistentVolumeClaim:
            claimName: sonarqube-temp
---
apiVersion: v1
kind: Service
metadata:
  name: sast-sonarqube
  namespace: ${NAMESPACE}
spec:
  type: NodePort
  selector:
    app: sast-sonarqube
  ports:
    - port: 9000
      targetPort: 9000
      nodePort: 30900
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: sast-repos
  namespace: ${NAMESPACE}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ci-utils-artifacts
  namespace: ${NAMESPACE}
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 10Gi
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sast-ci-utils
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sast-ci-utils
  template:
    metadata:
      labels:
        app: sast-ci-utils
    spec:
      nodeSelector:
        kubernetes.io/hostname: ${WORKER_HOSTNAME}
      serviceAccountName: ci-utils-sa
      containers:
        - name: ci-utils
          image: ${REGISTRY}/sast-ci-utils:${IMAGE_TAG}
          env:
            - name: ARTIFACTS_DIR
              value: "/data/artifacts"
            - name: SONAR_HOST
              value: "http://sast-sonarqube:9000"
            - name: GITLEAKS_IMAGE
              value: "${REGISTRY}/sast-gitleaks:${IMAGE_TAG}"
            - name: TRIVY_IMAGE
              value: "${REGISTRY}/sast-trivy:${IMAGE_TAG}"
            - name: SONAR_SCANNER_IMAGE
              value: "${REGISTRY}/sast-sonar-scanner:${IMAGE_TAG}"
          ports:
            - containerPort: 8080
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          volumeMounts:
            - name: repos-storage
              mountPath: /repos
            - name: artifacts-storage
              mountPath: /data/artifacts
      volumes:
        - name: repos-storage
          persistentVolumeClaim:
            claimName: sast-repos
        - name: artifacts-storage
          persistentVolumeClaim:
            claimName: ci-utils-artifacts
---
apiVersion: v1
kind: Service
metadata:
  name: sast-ci-utils
  namespace: ${NAMESPACE}
spec:
  type: NodePort
  selector:
    app: sast-ci-utils
  ports:
    - port: 8080
      targetPort: 8080
      nodePort: 30084
EOF

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Master setup complete"
echo "════════════════════════════════════════════════════════"
echo ""
echo "  Join command: /home/aotm/join-command.sh"
echo ""
echo "  NEXT STEPS:"
echo "  1. Login to private registry on worker:"
echo "     ssh aotm@192.168.13.176 'docker login container-registry.aotm.ai'"
echo "  2. scp /home/aotm/join-command.sh aotm@192.168.13.176:/home/aotm/"
echo "  3. scp worker-setup.sh aotm@192.168.13.176:/home/aotm/"
echo "  4. SSH into worker → sudo ./worker-setup.sh"
echo "  5. kubectl get nodes"
echo "  6. kubectl get pods -n sast -w"
echo "  7. SonarQube UI: http://192.168.13.173:30900"
echo "     Login: admin/admin → change password → create project → get token"
echo ""
kubectl get nodes 2>/dev/null || true

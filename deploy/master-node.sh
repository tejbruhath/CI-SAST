#!/usr/bin/env bash
###############################################################################
# SAST pipeline — MASTER node bootstrap (run on a fresh Ubuntu EC2).
#
# Images are built & pushed from your build machine to Docker Hub (public repos
# under tejbruhath/*). This node only PULLS them — no docker login here.
#
# Brings up: k8s control plane (kubeadm) + flannel + local-path storage,
# deploys Redis / Postgres / SonarQube / ci-utils, bootstraps SonarQube
# (project + token), runs the React+nginx frontend, installs & registers a
# GitLab runner, then prints the worker join command + tokens.
#
# Credentials (GitLab runner token) are PROMPTED at runtime — never stored.
# Run:  sudo ./master-node.sh        (from the repo's final/deploy directory)
###############################################################################
set -euo pipefail

REGISTRY="${REGISTRY:-tejbruhath}"          # Docker Hub namespace to pull from
POD_CIDR="10.244.0.0/16"
K8S_MINOR="1.29"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUDO_USER_HOME="$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)"

log()  { echo -e "\n\033[1;36m► $*\033[0m"; }
warn() { echo -e "\033[1;33m! $*\033[0m"; }
die()  { echo -e "\033[1;31m✗ $*\033[0m" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "run with sudo"

read -rp  "GitLab base URL the runner registers to (e.g. http://1.2.3.4:8929) [skip=blank]: " GITLAB_URL
if [ -n "$GITLAB_URL" ]; then
  read -rsp "GitLab runner registration token: " GITLAB_REG_TOKEN; echo
fi

# ---- 1. base packages (Ubuntu ships docker.io + containerd; 26.04 has no
#         docker-ce repo yet, and kubeadm only needs containerd anyway) --------
log "Installing base packages (docker.io, containerd, kubeadm/kubelet/kubectl, jq)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y docker.io docker-compose-v2 jq git curl gnupg apt-transport-https ca-certificates
systemctl enable --now docker
usermod -aG docker "${SUDO_USER:-root}" || true

mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${K8S_MINOR}/deb/Release.key" | gpg --batch --yes --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${K8S_MINOR}/deb/ /" \
  > /etc/apt/sources.list.d/kubernetes.list
apt-get update -y
apt-get install -y kubelet kubeadm kubectl
apt-mark hold kubelet kubeadm kubectl

# ---- 2. system prep --------------------------------------------------------
log "Kernel/sysctl prep (swap off, br_netfilter, vm.max_map_count for SonarQube ES)"
swapoff -a; sed -i '/ swap / s/^/#/' /etc/fstab || true
modprobe br_netfilter overlay || true
printf 'overlay\nbr_netfilter\n' >/etc/modules-load.d/k8s.conf
cat >/etc/sysctl.d/k8s.conf <<'EOF'
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
vm.max_map_count                    = 262144
EOF
sysctl --system >/dev/null

# containerd: enable CRI (Ubuntu's default disables it) + systemd cgroups
mkdir -p /etc/containerd
containerd config default >/etc/containerd/config.toml
sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
systemctl restart containerd

# ---- 3. control plane ------------------------------------------------------
if [ ! -f /etc/kubernetes/admin.conf ]; then
  log "kubeadm init (pod CIDR $POD_CIDR)"
  kubeadm init --pod-network-cidr="$POD_CIDR"
else
  warn "control plane already initialised, skipping kubeadm init"
fi
export KUBECONFIG=/etc/kubernetes/admin.conf
mkdir -p "$SUDO_USER_HOME/.kube"
cp -f /etc/kubernetes/admin.conf "$SUDO_USER_HOME/.kube/config"
chown "$(id -u "${SUDO_USER:-root}")":"$(id -g "${SUDO_USER:-root}")" "$SUDO_USER_HOME/.kube/config" || true

log "Installing flannel CNI"
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml

log "Labelling master node role=master"
kubectl label node "$(hostname)" sast.aotm/role=master --overwrite
# Drop the control-plane taint: every workload is pinned by nodeSelector, and the
# local-path provisioner's helper pod must be able to run on master to provision
# the SonarQube/Postgres PVs that live there.
kubectl taint nodes "$(hostname)" node-role.kubernetes.io/control-plane- 2>/dev/null || true

log "Installing local-path storage provisioner (default StorageClass)"
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.28/deploy/local-path-storage.yaml
kubectl patch storageclass local-path -p \
  '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'

# ---- 4. deploy manifests (images pulled from public Docker Hub) ------------
log "Applying k8s manifests (pulling $REGISTRY/* images)"
kubectl apply -f "$REPO_ROOT/k8s/00-namespace.yaml"

SONAR_DB_PASS="$(openssl rand -hex 16)"
kubectl -n sast-system create secret generic sonar-db \
  --from-literal=POSTGRES_PASSWORD="$SONAR_DB_PASS" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f "$REPO_ROOT/k8s/01-rbac.yaml"
kubectl apply -f "$REPO_ROOT/k8s/02-resourcequota.yaml"
kubectl apply -f "$REPO_ROOT/k8s/03-redis.yaml"
kubectl apply -f "$REPO_ROOT/k8s/04-pvcs.yaml"
kubectl apply -f "$REPO_ROOT/k8s/10-postgres.yaml"
kubectl apply -f "$REPO_ROOT/k8s/11-sonarqube.yaml"
sed "s#tejbruhath/#${REGISTRY}/#g" "$REPO_ROOT/k8s/20-ci-utils.yaml" | kubectl apply -f -

# ---- 5. wait for SonarQube + bootstrap ------------------------------------
# IMDSv2 is token-required on modern EC2; a plain GET gets HTTP 401 and, without
# -f, curl treats that as "success" and returns the error page as the body.
IMDS_TOKEN="$(curl -sf -m 2 -X PUT http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 21600' 2>/dev/null || true)"
MASTER_IP="$(curl -sf -m 2 ${IMDS_TOKEN:+-H "X-aws-ec2-metadata-token: $IMDS_TOKEN"} \
  http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
[ -n "$MASTER_IP" ] || MASTER_IP="$(hostname -I | awk '{print $1}')"

SONAR="http://localhost:30900"
# Design: ONE shared SonarQube project ("vulnapp") for every repo scanned,
# not one project per repo. This is safe because sonar-scanner polls its own
# specific ceTaskId and fetches issues immediately on that task's SUCCESS --
# SonarQube's Compute Engine processes analyses one at a time server-side
# even when multiple scanner pods submit concurrently, so results never get
# crossed between repos as long as each pod reads its own ceTaskId's result
# right after that task completes (which entrypoint.py already does).
SONAR_PROJECT_KEY="vulnapp"
SONAR_PASS_FILE="$REPO_ROOT/deploy/.sonar-admin-pass"
SONAR_TOKEN_FILE="$REPO_ROOT/deploy/.sonar-token"

log "Waiting for SonarQube UP (cold start on small instances can take 10-15 min)…"
st=DOWN
for i in $(seq 1 90); do
  if kubectl logs -n sast-system deploy/sonarqube --since=20m 2>/dev/null | grep -q "SonarQube is operational"; then
    st=UP; break
  fi
  st="$(curl -s "$SONAR/api/system/status" | jq -r '.status // "DOWN"' 2>/dev/null || echo DOWN)"
  [ "$st" = "UP" ] && break
  sleep 10
done

SONAR_TOKEN=""
if [ "$st" != "UP" ]; then
  warn "SonarQube not UP yet -- skipping project/token bootstrap, set up manually and re-run"
else
  # Never trust a cached password blindly -- a PVC wipe or manual reset (like
  # this one) invalidates it silently otherwise.
  sonar_auth_ok() {
    [ -n "$1" ] && curl -s -o /dev/null -w '%{http_code}' -u "admin:$1" \
      "$SONAR/api/authentication/validate" | grep -q '^200$'
  }

  SONAR_ADMIN_PASS=""
  if [ -f "$SONAR_PASS_FILE" ] && sonar_auth_ok "$(cat "$SONAR_PASS_FILE")"; then
    SONAR_ADMIN_PASS="$(cat "$SONAR_PASS_FILE")"
    log "Reusing cached SonarQube admin password (validated live)"
  elif sonar_auth_ok admin; then
    NEW_PASS="$(openssl rand -hex 12)"
    # This endpoint has been observed to 401 Basic Auth on some SonarQube
    # patch builds even with valid admin:admin creds (CSRF/session quirk) --
    # no -f here, and don't let a failed rotation take the whole script down
    # (it did, silently, before this guard existed): fall back to the
    # still-valid "admin" password instead of crashing.
    ROTATE_STATUS="$(curl -s -o /dev/null -w '%{http_code}' -u admin:admin -X POST \
      "$SONAR/api/users/change_password?login=admin&previousPassword=admin&password=$NEW_PASS")"
    if [ "$ROTATE_STATUS" = "200" ] || [ "$ROTATE_STATUS" = "204" ]; then
      SONAR_ADMIN_PASS="$NEW_PASS"
      log "Rotated default admin password"
    else
      SONAR_ADMIN_PASS="admin"
      warn "SonarQube rejected the password-rotation request (HTTP $ROTATE_STATUS) -- leaving it as admin/admin, rotate manually if desired"
    fi
    echo "$SONAR_ADMIN_PASS" > "$SONAR_PASS_FILE"; chmod 600 "$SONAR_PASS_FILE"
  else
    read -rsp "SonarQube admin password was already changed manually -- enter it once so I can bootstrap the project/token: " SONAR_ADMIN_PASS
    echo
    echo "$SONAR_ADMIN_PASS" > "$SONAR_PASS_FILE"; chmod 600 "$SONAR_PASS_FILE"
  fi

  if [ -f "$SONAR_TOKEN_FILE" ]; then
    SONAR_TOKEN="$(cat "$SONAR_TOKEN_FILE")"
    log "Reusing cached SonarQube project token"
  elif [ -n "$SONAR_ADMIN_PASS" ]; then
    curl -s -u "admin:$SONAR_ADMIN_PASS" -X POST \
      "$SONAR/api/projects/create?name=$SONAR_PROJECT_KEY&project=$SONAR_PROJECT_KEY" >/dev/null || true
    SONAR_TOKEN="$(curl -s -u "admin:$SONAR_ADMIN_PASS" -X POST \
      "$SONAR/api/user_tokens/generate?name=ci-bootstrap" | jq -r '.token // empty')"
    if [ -n "$SONAR_TOKEN" ]; then
      echo "$SONAR_TOKEN" > "$SONAR_TOKEN_FILE"; chmod 600 "$SONAR_TOKEN_FILE"
      log "Created SonarQube project '$SONAR_PROJECT_KEY' + token"
    else
      warn "Project/token creation failed -- check admin password, create manually if needed"
    fi
  fi
fi

# ---- 6. frontend (HTTP-only, pulls $REGISTRY/sast-frontend) ---------------
log "Starting frontend (React + nginx) on :80"
sed "s#tejbruhath/#${REGISTRY}/#g" "$REPO_ROOT/deploy/frontend.compose.yml" \
  > "$REPO_ROOT/deploy/frontend.compose.rendered.yml"
docker compose -f "$REPO_ROOT/deploy/frontend.compose.rendered.yml" up -d 2>/dev/null \
  || docker-compose -f "$REPO_ROOT/deploy/frontend.compose.rendered.yml" up -d

# ---- 7. GitLab runner (optional) ------------------------------------------
# Idempotency guard: re-running this script used to call `gitlab-runner
# register` unconditionally every time, piling up duplicate runner entries in
# config.toml on every re-run (all sharing the sast-aws tag, so GitLab would
# round-robin jobs across old and new registrations alike). Skip if a runner
# for this URL is already registered; unregister manually first if you want
# to force a clean re-registration.
if [ -n "$GITLAB_URL" ]; then
  if [ -f /etc/gitlab-runner/config.toml ] && grep -q "url = \"$GITLAB_URL\"" /etc/gitlab-runner/config.toml; then
    warn "a runner for $GITLAB_URL is already registered -- skipping (gitlab-runner list / unregister first to redo)"
  else
    log "Installing + registering GitLab runner (docker executor, tag sast-aws)"
    curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | bash
    apt-get install -y gitlab-runner
    gitlab-runner register --non-interactive --url "$GITLAB_URL" \
      --registration-token "$GITLAB_REG_TOKEN" --executor docker \
      --docker-image "alpine:3.20" --description "sast-aws-runner" \
      --tag-list "sast-aws" --run-untagged="false" --locked="false" \
      || warn "runner registration failed (check URL/token/reachability)"
  fi
fi

# ---- 8. worker join + summary ---------------------------------------------
JOIN_CMD="$(kubeadm token create --print-join-command)"
echo "$JOIN_CMD" > "$REPO_ROOT/deploy/worker-join-command.txt"
cat <<EOF

════════════════════════════════════════════════════════════════════
  MASTER READY
════════════════════════════════════════════════════════════════════
  Frontend    : http://$MASTER_IP/
  SonarQube   : http://$MASTER_IP:30900/
  ci-utils    : http://$MASTER_IP:30084/health

  Sonar project: $SONAR_PROJECT_KEY   token: ${SONAR_TOKEN:-<not bootstrapped -- see warning above, set up manually>}
  Put these into GitLab CI/CD variables as SONAR_PROJECT_KEY / SONAR_TOKEN,
  alongside CI_UTILS_URL.

  WORKER JOIN (also saved to deploy/worker-join-command.txt):
  $JOIN_CMD
════════════════════════════════════════════════════════════════════
EOF

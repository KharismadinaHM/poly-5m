#!/usr/bin/env bash
# =============================================================================
# deploy_gcp.sh — Setup lengkap bot trading Polymarket di Google Cloud Platform
#
# Prasyarat:
#   - gcloud CLI sudah terinstall & login: gcloud auth login
#   - Docker sudah terinstall
#   - Sudah punya GCP project
#
# Cara pakai:
#   chmod +x deploy_gcp.sh
#   ./deploy_gcp.sh
# =============================================================================
set -euo pipefail

# ── KONFIGURASI — sesuaikan bagian ini ───────────────────────────────────────
PROJECT_ID="your-gcp-project-id"        # ganti dengan project ID kamu
REGION="asia-southeast1"                # Singapore — paling dekat dari Indonesia
ZONE="${REGION}-b"
VM_NAME="polymarket-bot"
MACHINE_TYPE="e2-micro"                 # ~$6/bulan; naik ke e2-small jika butuh lebih
REPO_NAME="polymarket-bot-repo"
IMAGE_NAME="polymarket-bot"
IMAGE_TAG="latest"
# ─────────────────────────────────────────────────────────────────────────────

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "================================================="
echo "  Deploy Polymarket Bot ke GCP"
echo "  Project : ${PROJECT_ID}"
echo "  Region  : ${REGION}"
echo "  VM      : ${VM_NAME}"
echo "================================================="

# ── STEP 1: Set project aktif ─────────────────────────────────────────────────
echo ""
echo "[1/7] Set project GCP..."
gcloud config set project "${PROJECT_ID}"

# ── STEP 2: Enable APIs yang diperlukan ───────────────────────────────────────
echo ""
echo "[2/7] Mengaktifkan GCP APIs..."
gcloud services enable \
  artifactregistry.googleapis.com \
  compute.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com

echo "      APIs aktif."

# ── STEP 3: Simpan secrets ke Secret Manager ──────────────────────────────────
echo ""
echo "[3/7] Menyimpan secrets ke Secret Manager..."
echo "      (Kamu akan diminta mengisi nilai masing-masing secret)"

store_secret() {
  local name="$1"
  local prompt="$2"
  echo -n "      ${prompt}: "
  read -rs value
  echo ""
  # Buat secret jika belum ada
  if ! gcloud secrets describe "${name}" &>/dev/null; then
    gcloud secrets create "${name}" --replication-policy="automatic" --quiet
  fi
  echo -n "${value}" | gcloud secrets versions add "${name}" --data-file=-
  echo "      [OK] ${name} tersimpan."
}

store_secret "POLY_API_KEY"        "Polymarket API Key"
store_secret "POLY_API_SECRET"     "Polymarket API Secret"
store_secret "POLY_API_PASSPHRASE" "Polymarket API Passphrase"
store_secret "PRIVATE_KEY"        "EVM Private Key (tanpa 0x)"

# Secret non-sensitif langsung sebagai env var (tidak perlu Secret Manager)
echo ""
echo "      Konfigurasi tambahan (tekan Enter untuk default):"
read -rp "      MAX_BET_USDC [10.0]: " MAX_BET
read -rp "      DRY_RUN [true]: " DRY_RUN_VAL
MAX_BET="${MAX_BET:-10.0}"
DRY_RUN_VAL="${DRY_RUN_VAL:-true}"

# ── STEP 4: Buat Artifact Registry & push Docker image ───────────────────────
echo ""
echo "[4/7] Build & push Docker image..."

# Buat repository jika belum ada
if ! gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" &>/dev/null; then
  gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Polymarket trading bot images"
  echo "      Repository '${REPO_NAME}' dibuat."
fi

# Auth Docker ke Artifact Registry
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# Build & push
docker build -t "${IMAGE_URI}" .
docker push "${IMAGE_URI}"
echo "      Image berhasil dipush: ${IMAGE_URI}"

# ── STEP 5: Buat Service Account dengan izin minimal ─────────────────────────
echo ""
echo "[5/7] Setup Service Account..."
SA_NAME="polymarket-bot-sa"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "${SA_EMAIL}" &>/dev/null; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Polymarket Bot Service Account"
fi

# Grant izin: baca secrets & tulis log saja
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/logging.logWriter" --quiet

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/monitoring.metricWriter" --quiet

echo "      Service Account siap: ${SA_EMAIL}"

# ── STEP 6: Buat & konfigurasi VM ────────────────────────────────────────────
echo ""
echo "[6/7] Membuat Compute Engine VM..."

# Buat startup script yang menarik secrets dari Secret Manager
STARTUP_SCRIPT=$(cat <<'SCRIPT'
#!/bin/bash
# Startup script VM — dijalankan sekali saat VM boot

# Install Docker jika belum ada
if ! command -v docker &>/dev/null; then
  apt-get update -q
  apt-get install -y docker.io
  systemctl enable docker
  systemctl start docker
fi

# Konfigurasi Docker agar bisa pull dari Artifact Registry
gcloud auth configure-docker REGION-docker.pkg.dev --quiet

# Buat systemd service untuk bot agar restart otomatis
cat > /etc/systemd/system/polymarket-bot.service <<EOF
[Unit]
Description=Polymarket Trading Bot
After=docker.service network-online.target
Requires=docker.service

[Service]
Restart=always
RestartSec=10
ExecStartPre=-/usr/bin/docker stop polymarket-bot
ExecStartPre=-/usr/bin/docker rm polymarket-bot
ExecStart=/usr/bin/docker run --rm --name polymarket-bot \
  --log-driver=gcplogs \
  -e POLY_API_KEY=$(gcloud secrets versions access latest --secret=POLY_API_KEY) \
  -e POLY_API_SECRET=$(gcloud secrets versions access latest --secret=POLY_API_SECRET) \
  -e POLY_API_PASSPHRASE=$(gcloud secrets versions access latest --secret=POLY_API_PASSPHRASE) \
  -e PRIVATE_KEY=$(gcloud secrets versions access latest --secret=PRIVATE_KEY) \
  -e DRY_RUN=DRY_RUN_PLACEHOLDER \
  -e MAX_BET_USDC=MAX_BET_PLACEHOLDER \
  IMAGE_URI_PLACEHOLDER
ExecStop=/usr/bin/docker stop polymarket-bot

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable polymarket-bot
systemctl start polymarket-bot
SCRIPT
)

# Substitusi nilai ke dalam startup script
STARTUP_SCRIPT="${STARTUP_SCRIPT//REGION/${REGION}}"
STARTUP_SCRIPT="${STARTUP_SCRIPT//IMAGE_URI_PLACEHOLDER/${IMAGE_URI}}"
STARTUP_SCRIPT="${STARTUP_SCRIPT//DRY_RUN_PLACEHOLDER/${DRY_RUN_VAL}}"
STARTUP_SCRIPT="${STARTUP_SCRIPT//MAX_BET_PLACEHOLDER/${MAX_BET}}"

# Buat VM
gcloud compute instances create "${VM_NAME}" \
  --zone="${ZONE}" \
  --machine-type="${MACHINE_TYPE}" \
  --image-family="debian-12" \
  --image-project="debian-cloud" \
  --service-account="${SA_EMAIL}" \
  --scopes="cloud-platform" \
  --no-address \
  --metadata="startup-script=${STARTUP_SCRIPT}" \
  --tags="polymarket-bot" \
  --quiet

echo "      VM '${VM_NAME}' berhasil dibuat di zone ${ZONE}."

# Firewall: hanya egress keluar, blokir semua ingress
gcloud compute firewall-rules create "deny-ingress-${VM_NAME}" \
  --direction=INGRESS \
  --priority=1000 \
  --action=DENY \
  --rules=all \
  --target-tags="polymarket-bot" \
  --quiet 2>/dev/null || echo "      Firewall rule sudah ada, dilewati."

# ── STEP 7: Setup monitoring alert ───────────────────────────────────────────
echo ""
echo "[7/7] Menyiapkan uptime monitoring..."
echo "      Buka Cloud Monitoring > Alerting > Create Policy"
echo "      Metric: compute.googleapis.com/instance/uptime"
echo "      Condition: VM ${VM_NAME} uptime < 1 menit → kirim email alert"
echo ""
echo "================================================="
echo "  DEPLOY SELESAI!"
echo ""
echo "  Cek status bot:"
echo "  gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='systemctl status polymarket-bot'"
echo ""
echo "  Lihat log real-time:"
echo "  gcloud logging read 'resource.type=gce_instance AND resource.labels.instance_id=${VM_NAME}' --limit=50 --format=json"
echo ""
echo "  Update image bot (setelah rebuild):"
echo "  gcloud compute instances reset ${VM_NAME} --zone=${ZONE}"
echo "================================================="

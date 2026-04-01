# Polymarket Trading Bot — Panduan GCP

## Pilihan Deploy

| | Compute Engine VM | Cloud Run Jobs |
|---|---|---|
| Model bayar | ~$6/bulan (always-on) | Per eksekusi |
| Cocok untuk | Bot yang terus berjalan | Bot periodik |
| Kompleksitas | Sedang | Rendah |
| Kontrol | Penuh | Terbatas |

**Rekomendasi:** Gunakan **Compute Engine** karena bot ini perlu memantau market secara real-time dan bereaksi dalam 10 detik terakhir — Cloud Run terlalu lambat untuk cold-start dalam jendela waktu sekecil itu.

---

## Prasyarat

```bash
# Install gcloud CLI
# https://cloud.google.com/sdk/docs/install

# Login
gcloud auth login
gcloud auth application-default login

# Install Docker
# https://docs.docker.com/get-docker/
```

---

## Deploy ke Compute Engine (Rekomendasi)

```bash
# 1. Clone & masuk ke folder bot
cd polymarket_bot

# 2. Edit PROJECT_ID di script
nano deploy_gcp.sh   # ubah "your-gcp-project-id"

# 3. Jalankan
chmod +x deploy_gcp.sh
./deploy_gcp.sh
```

Script akan secara otomatis:
- Mengaktifkan API GCP yang diperlukan
- Menyimpan credentials ke **Secret Manager** (tidak pernah di `.env` di server)
- Build & push Docker image ke **Artifact Registry**
- Membuat **Service Account** dengan izin minimal (principle of least privilege)
- Membuat VM dengan **systemd** agar bot restart otomatis jika crash
- Mengunci firewall: **egress only**, tidak ada SSH terbuka ke publik

---

## Deploy ke Cloud Run Jobs (Alternatif)

```bash
# Pastikan image sudah dipush (jalankan bagian build dari deploy_gcp.sh dulu)

chmod +x deploy_cloudrun.sh
./deploy_cloudrun.sh
```

---

## Perintah Operasional

### Cek status bot
```bash
gcloud compute ssh polymarket-bot \
  --zone=asia-southeast1-b \
  --command="systemctl status polymarket-bot"
```

### Lihat log real-time
```bash
# Via Cloud Logging
gcloud logging read \
  'resource.type=gce_instance AND jsonPayload.message!=""' \
  --limit=50 --format="value(jsonPayload.message)"

# Atau langsung di VM
gcloud compute ssh polymarket-bot \
  --zone=asia-southeast1-b \
  --command="docker logs -f polymarket-bot"
```

### Update bot (setelah ubah kode)
```bash
# Rebuild & push image baru
docker build -t REGION-docker.pkg.dev/PROJECT/repo/polymarket-bot:latest .
docker push REGION-docker.pkg.dev/PROJECT/repo/polymarket-bot:latest

# Restart VM agar pull image terbaru
gcloud compute instances reset polymarket-bot --zone=asia-southeast1-b
```

### Ganti API key
```bash
# Tambah versi baru di Secret Manager
echo -n "NEW_KEY_VALUE" | gcloud secrets versions add POLY_API_KEY --data-file=-

# Restart bot
gcloud compute instances reset polymarket-bot --zone=asia-southeast1-b
```

### Matikan bot sementara
```bash
gcloud compute instances stop polymarket-bot --zone=asia-southeast1-b
# Hidupkan kembali:
gcloud compute instances start polymarket-bot --zone=asia-southeast1-b
```

---

## Biaya Estimasi (asia-southeast1)

| Komponen | Spek | Biaya/bulan |
|---|---|---|
| Compute Engine | e2-micro | ~$6 |
| Artifact Registry | <1 GB | ~$0.10 |
| Secret Manager | 6 akses/hari | ~$0 |
| Cloud Logging | <1 GB/bulan | ~$0 |
| **Total** | | **~$6–7/bulan** |

---

## Keamanan

- Credentials **hanya** disimpan di Secret Manager — tidak ada file `.env` di server
- VM tidak punya IP publik (egress-only)
- Service Account hanya punya izin: `secretmanager.secretAccessor`, `logging.logWriter`, `monitoring.metricWriter`
- Docker image dijalankan sebagai user non-root (`botuser`)
- `DRY_RUN=true` secara default — set ke `false` hanya saat siap trading nyata

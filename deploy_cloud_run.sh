#!/usr/bin/env bash
set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID gerekli}"
: "${REGION:=europe-west1}"
: "${SERVICE_NAME:=sirra-api}"
: "${SERVICE_ACCOUNT:?SERVICE_ACCOUNT gerekli; örn: sirra-backend@${PROJECT_ID}.iam.gserviceaccount.com}"

if [ ! -f cloudrun.env.yaml ]; then
  echo "[HATA] cloudrun.env.yaml bulunamadı. cloudrun.env.example.yaml dosyasını kopyalayıp alan adlarını düzenle."
  exit 1
fi

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com firestore.googleapis.com identitytoolkit.googleapis.com androidpublisher.googleapis.com texttospeech.googleapis.com

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --service-account "$SERVICE_ACCOUNT" \
  --env-vars-file cloudrun.env.yaml \
  --set-secrets "OPENAI_API_KEY=SIRRA_OPENAI_API_KEY:latest,REVENUECAT_WEBHOOK_SECRET=SIRRA_REVENUECAT_WEBHOOK_SECRET:latest" \
  --cpu 1 \
  --memory 1Gi \
  --concurrency 40 \
  --timeout 120 \
  --min 0 \
  --max 10 \
  --cpu-boost

echo
echo "Backend URL:"
gcloud run services describe "$SERVICE_NAME" --region "$REGION" --format='value(status.url)'

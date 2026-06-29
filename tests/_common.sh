# Sourced by every script in this folder. Pinned URL → no .env dependency,
# so scripts run from any directory. Token is fetched live via gcloud.
URL="${URL:-https://truthfulness-unified-fq5fpdmt7a-uc.a.run.app}"
TOKEN="${TOKEN:-$(gcloud auth print-identity-token)}"

if [ -z "$TOKEN" ]; then
  echo "❌ gcloud auth print-identity-token returned empty — run \`gcloud auth login\`"
  exit 1
fi

echo "▶ URL:   $URL"
echo "▶ Token: ${#TOKEN} chars"
echo

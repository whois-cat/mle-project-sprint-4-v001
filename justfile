set dotenv-load := true


DATA_DIR := "data"
ARTIFACTS_DIR := "artifacts"
NOTEBOOK_OUT_DIR := "artifacts/notebook_runs"

TRACKS_URL := "https://storage.yandexcloud.net/mle-data/ym/tracks.parquet"
CATALOG_URL := "https://storage.yandexcloud.net/mle-data/ym/catalog_names.parquet"
EVENTS_URL := "https://storage.yandexcloud.net/mle-data/ym/interactions.parquet"

dirs:
  mkdir -p "{{DATA_DIR}}"
  mkdir -p "{{ARTIFACTS_DIR}}"
  mkdir -p "{{NOTEBOOK_OUT_DIR}}"

bootstrap: uv-sync data dirs

uv-sync:
  uv sync

download url filename:
  mkdir -p "{{DATA_DIR}}"
  if [ -s "{{DATA_DIR}}/{{filename}}" ]; then exit 0; fi
  curl -fL --retry 5 --retry-delay 2 --connect-timeout 20 \
    "{{url}}" -o "{{DATA_DIR}}/{{filename}}.tmp"
  mv "{{DATA_DIR}}/{{filename}}.tmp" "{{DATA_DIR}}/{{filename}}"

data: dirs
  just download "{{TRACKS_URL}}" "tracks.parquet"
  just download "{{CATALOG_URL}}" "catalog_names.parquet"
  just download "{{EVENTS_URL}}" "interactions.parquet"

up:
  echo "starting containers in the background..."
  docker compose up --build -d

test:
  pytest -v

reload:
  curl -f -X POST "http://localhost:8000/reload" -H "X-Reload-Token: {{env_var('RELOAD_TOKEN')}}"

down:
  echo "stopping and removing containers..."
  docker compose down --remove-orphans

logs:
  echo "viewing logs..."
  docker compose logs -f

shell service:
  echo "opening a shell in the {{service}} container..."
  docker compose exec -it {{service}} bash

default:
  just --list
    
s3-env-check:
    test -n "${S3_ENDPOINT_URL:-}"
    test -n "${S3_BUCKET_NAME:-}"
    test -n "${AWS_ACCESS_KEY_ID:-}"
    test -n "${AWS_SECRET_ACCESS_KEY:-}"
    @echo "S3 env looks set"

notebook-run NOTEBOOK="recommendations.ipynb":
    mkdir -p "{{NOTEBOOK_OUT_DIR}}"
    uv run jupyter nbconvert --to notebook --execute \
      --ExecutePreprocessor.timeout=-1 \
      --output-dir "{{NOTEBOOK_OUT_DIR}}" \
      --output "$(basename "{{NOTEBOOK}}" .ipynb).executed.ipynb" \
      "{{NOTEBOOK}}"

do-it: dirs up
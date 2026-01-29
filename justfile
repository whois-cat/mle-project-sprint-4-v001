set dotenv-load
set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

DATA_DIR := "data"
ARTIFACTS_DIR := "artifacts"
NOTEBOOK_OUT_DIR := "artifacts/notebook_runs"

APP_HOST := env("APP_HOST", "127.0.0.1")
APP_PORT := env("APP_PORT", "8000")
BASE_URL := "http://" + APP_HOST + ":" + APP_PORT

TRACKS_URL := "https://storage.yandexcloud.net/mle-data/ym/tracks.parquet"
CATALOG_URL := "https://storage.yandexcloud.net/mle-data/ym/catalog_names.parquet"
EVENTS_URL := "https://storage.yandexcloud.net/mle-data/ym/interactions.parquet"

dirs:
  mkdir -p "{{DATA_DIR}}" "{{ARTIFACTS_DIR}}" "{{NOTEBOOK_OUT_DIR}}"

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
  docker compose up --build -d

down:
  docker compose down --remove-orphans

logs:
  docker compose logs -f

shell service:
  docker compose exec -it {{service}} bash

health:
  curl -fsS "{{BASE_URL}}/health" | python -m json.tool

reload:
  curl -f -X POST "{{BASE_URL}}/reload" -H "X-Reload-Token: {{env_var('RELOAD_TOKEN')}}"

test:
  pytest -q

warm:
  uv run python warm_history.py --users 20 --rounds 3 --seed-take 5

default:
  just --list

bootstrap: uv-sync dirs data

all: bootstrap up health test
  @echo "OK"

smoke:
  just up
  just health
  just test
  just down

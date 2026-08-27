#!/usr/bin/env bash
set -euo pipefail

source_dir=${1:?source dir required}
build_dir=${2:?build dir required}
pdf_dir=${3:-$build_dir/pdfs}
pdf_timeout_ms=${SLIDES_PDF_TIMEOUT_MS:-120000}
requested_doc_count=$#
if [ "$#" -ge 3 ]; then
  shift 3
else
  shift "$#"
fi

extract_yaml_scalar() {
  local key="$1"
  local file="$2"

  awk -v key="$key" '
    BEGIN {
      in_yaml = 0
      pattern = "^" key ":[[:space:]]*"
    }
    NR == 1 && $0 == "---" {
      in_yaml = 1
      next
    }
    in_yaml && $0 == "---" {
      exit
    }
    in_yaml && $0 ~ pattern {
      sub(pattern, "", $0)
      gsub(/^["'"'"']|["'"'"']$/, "", $0)
      print $0
      exit
    }
  ' "$file"
}

find_browser() {
  if [ -n "${BROWSER:-}" ] && command -v "$BROWSER" >/dev/null 2>&1; then
    command -v "$BROWSER"
    return 0
  fi

  for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  return 1
}

find_node() {
  if command -v node >/dev/null 2>&1; then
    printf '%s\n' node
    return 0
  fi
  return 1
}

cleanup() {
  kill "${server_pid:-}" 2>/dev/null || true
}

docs=()
if [ "$#" -gt 0 ]; then
  for doc in "$@"; do
    case "$doc" in
      /*)
        case "$doc" in
          *.qmd) docs+=("$doc") ;;
          *) docs+=("$doc.qmd") ;;
        esac
        ;;
      *)
        case "$doc" in
          *.qmd) docs+=("$source_dir/$doc") ;;
          *) docs+=("$source_dir/$doc.qmd") ;;
        esac
        ;;
    esac
  done
else
  shopt -s nullglob
  while IFS= read -r -d '' doc; do
    docs+=("$doc")
  done < <(find "$source_dir" -maxdepth 1 -type f -name '*.qmd' -print0)
fi

if [ "${#docs[@]}" -eq 0 ]; then
  echo "No slide decks found"
  exit 0
fi

trap cleanup EXIT

browser=$(find_browser) || {
  echo "No Chrome/Chromium browser found for PDF export" >&2
  exit 1
}

node_bin=$(find_node) || {
  echo "No node binary found for PDF export" >&2
  exit 1
}

if [ "$requested_doc_count" -le 3 ]; then
  rm -rf "$pdf_dir"
fi
mkdir -p "$pdf_dir"

port="${PORT:-8008}"
server_log="${RUNNER_TEMP:-/tmp}/slides-pdf-server.log"
python3 -m http.server "$port" --directory "$build_dir" >"$server_log" 2>&1 &
server_pid=$!

sleep 2

for doc in "${docs[@]}"; do
  base=$(basename "$doc" .qmd)
  course=$(extract_yaml_scalar course "$doc")

  if [ -z "${course:-}" ]; then
    course="${SLIDES_COURSE_CODE:-CST334}"
  fi

  if [ ! -f "$build_dir/$base.html" ]; then
    echo "Missing rendered HTML for $doc" >&2
    exit 1
  fi

  course_pdf_dir="$pdf_dir/$course"
  mkdir -p "$course_pdf_dir"

  output_pdf="$course_pdf_dir/$base.pdf"
  slide_url="http://127.0.0.1:$port/$base.html?print-pdf"

  echo "Printing $doc to $output_pdf"
  "$node_bin" scripts/render_reveal_pdf.mjs \
    --browser "$browser" \
    --url "$slide_url" \
    --out "$output_pdf" \
    --timeout-ms "$pdf_timeout_ms"

  if [ ! -s "$output_pdf" ]; then
    echo "Missing rendered PDF for $doc" >&2
    exit 1
  fi
done

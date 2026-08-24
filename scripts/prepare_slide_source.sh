#!/usr/bin/env bash
set -euo pipefail

source_dir=${1:?source dir required}
render_dir=${2:?render dir required}

rm -rf "$render_dir"
mkdir -p "$render_dir"

# A course may opt into slide publishing after it is generated from this
# template. Make a manually-dispatched workflow a no-op until that directory
# exists rather than failing while attempting to copy its project files.
if [ ! -d "$source_dir" ]; then
  echo "Slide source directory '$source_dir' does not exist; nothing to prepare."
  exit 0
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

get_last_updated() {
  local file="$1"
  local rel_file="$file"
  local date_value

  case "$rel_file" in
    "$source_dir"/*)
      rel_file=${rel_file#"$source_dir"/}
      ;;
  esac

  if date_value=$(git -C "$source_dir" log -1 --format=%cd --date=format:'%Y-%m-%d %H:%M' -- "$rel_file" 2>/dev/null) && \
    git -C "$source_dir" diff --quiet -- "$rel_file" && \
    git -C "$source_dir" diff --cached --quiet -- "$rel_file"; then
    printf '%s\n' "$date_value"
    return 0
  fi

  date +'%Y-%m-%d %H:%M'
}

inject_last_updated() {
  local src="$1"
  local dest="$2"
  local last_updated="$3"

  awk -v last_updated="$last_updated" '
    BEGIN {
      in_yaml = 0
      inserted = 0
    }
    NR == 1 && $0 == "---" {
      in_yaml = 1
      print $0
      next
    }
    in_yaml && $0 ~ /^last_updated:[[:space:]]*/ {
      next
    }
    in_yaml && $0 == "---" {
      print "last_updated: \"" last_updated "\""
      print $0
      inserted = 1
      in_yaml = 0
      next
    }
    { print }
  ' "$src" > "$dest"
}

inject_beta_warning() {
  local src="$1"
  local dest="$2"
  local last_updated="$3"

  awk -v last_updated="$last_updated" '
    BEGIN {
      in_yaml = 0
      injected = 0
    }
    NR == 1 && $0 == "---" {
      in_yaml = 1
      print $0
      print "title-slide: false"
      print "last_updated: \"" last_updated "\""
      next
    }
    in_yaml && $0 == "---" && !injected {
      print $0
      print ""
      print "::: {.draft-slide}"
      print ""
      print "# DRAFT"
      print ""
      print "This slide deck is still under active development."
      print "Expect changes before it is finalized."
      print ""
      print ":::"
      print ""
      injected = 1
      next
    }
    { print }
  ' "$src" > "$dest"
}

cp "$source_dir/_quarto.yml" "$render_dir/_quarto.yml"
cp "$source_dir/.gitignore" "$render_dir/.gitignore" 2>/dev/null || true

if [ -d "$source_dir/assets" ]; then
  rsync -a --delete "$source_dir/assets/" "$render_dir/assets/"
fi

# Custom Quarto formats are resolved relative to the project directory. Keep
# the extension alongside the generated project so `lectures-revealjs` remains
# available when the workflow renders from its temporary source directory.
if [ -d "$source_dir/_extensions" ]; then
  rsync -a --delete "$source_dir/_extensions/" "$render_dir/_extensions/"
fi

docs=()
shopt -s nullglob
while IFS= read -r -d '' doc; do
  docs+=("$doc")
# Publishable decks live directly in slides/. Subdirectories hold supporting
# material (such as extensions and in-progress decks) and are not rendered.
done < <(find "$source_dir" -maxdepth 1 -type f -name '*.qmd' -print0)

for doc in "${docs[@]}"; do
  base=$(basename "$doc")
  draft_state=$(extract_yaml_scalar draft_state "$doc")
  last_updated=$(get_last_updated "$doc")

  case "${draft_state:-final}" in
    alpha)
      continue
      ;;
    beta)
      inject_beta_warning "$doc" "$render_dir/$base" "$last_updated"
      ;;
    final|"")
      inject_last_updated "$doc" "$render_dir/$base" "$last_updated"
      ;;
    *)
      echo "Unknown draft_state '$draft_state' in $doc" >&2
      exit 1
      ;;
  esac
done

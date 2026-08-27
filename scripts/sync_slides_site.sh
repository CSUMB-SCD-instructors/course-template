#!/usr/bin/env bash
set -euo pipefail

source_dir=${1:?source dir required}
build_dir=${2:?build dir required}
target_repo=${3:?target repo required}
shift 3

rendered_docs=()
if [ "$#" -gt 0 ]; then
  for doc in "$@"; do
    name=$(basename "$doc")
    rendered_docs+=("${name%.qmd}")
  done
fi

is_rendered_doc() {
  local candidate="$1"
  local rendered_doc

  for rendered_doc in "${rendered_docs[@]}"; do
    if [ "$rendered_doc" = "$candidate" ]; then
      return 0
    fi
  done

  return 1
}

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

sanitize_path_component() {
  printf '%s' "$1" | sed -E 's/[^A-Za-z0-9]+/-/g; s/^-+//; s/-+$//'
}

copy_file() {
  local src="$1"
  local dest="$2"

  if [ -f "$src" ]; then
    mkdir -p "$(dirname "$dest")"
    install -m 644 "$src" "$dest"
  fi
}

copy_dir() {
  local src="$1"
  local dest="$2"

  if [ -d "$src" ]; then
    mkdir -p "$dest"
    rsync -a --delete "$src/" "$dest/"
  fi
}

prune_legacy_root_outputs() {
  local root="$1"

  find "$root" -maxdepth 1 -type f \( -name '*.html' -o -name 'styles.css' \) -delete
  find "$root" -maxdepth 1 -type d -name '*_files' -prune -exec rm -rf {} +
  rm -rf "$root/assets"
}

write_root_index() {
  local publish_root="$1"
  local index_file="$publish_root/index.md"
  local course_dir
  local course
  local count

  {
    printf '%s\n' '---'
    printf '%s\n' 'layout: default'
    printf '%s\n' 'title: Slide Decks'
    printf '%s\n' '---'
    printf '\n# Slide Decks\n\n'
    printf 'Browse slide decks by class.\n\n'
    printf '| Class | Decks |\n'
    printf '| --- | ---: |\n'

    for course_dir in "$publish_root"/*; do
      [ -d "$course_dir" ] || continue
      course=$(basename "$course_dir")
      count=$(find "$course_dir" -maxdepth 1 -type f -name '*.html' | wc -l | tr -d '[:space:]')
      [ "$count" -gt 0 ] || continue
      printf '| [%s](%s/) | %d |\n' "$course" "$course" "$count"
    done
  } > "$index_file"
}

write_course_index() {
  local publish_root="$1"
  local course="$2"
  local manifest="$3"
  local course_dir="$publish_root/$course"
  local index_file="$course_dir/index.md"
  local tab

  tab=$(printf '\t')

  {
    printf '%s\n' '---'
    printf '%s\n' 'layout: default'
    printf 'title: "%s Slides"\n' "$course"
    printf '%s\n' '---'
    printf '\n# %s Slides\n\n' "$course"
    printf 'Available decks for %s.\n\n' "$course"
    printf 'PDF handouts are available in [pdfs/](pdfs/).\n\n'
    printf '| Deck | State | HTML | PDF |\n'
    printf '| --- | --- | --- | --- |\n'

    # The source filename carries the deck sequence (for example, 00- and
    # 01-), whereas presentation titles are descriptive and need not sort in
    # teaching order.
    sort -t "$tab" -k2,2 -k4,4 "$manifest" | awk -F '\t' -v course="$course" '
      $1 == course {
        printf("| %s | %s | [Open](%s.html) | [PDF](pdfs/%s) |\n", $7, $5, $2, $8)
      }
    '
  } > "$index_file"
}

write_course_pdf_index() {
  local publish_root="$1"
  local course="$2"
  local manifest="$3"
  local course_dir="$publish_root/$course/pdfs"
  local index_file="$course_dir/index.md"
  local tab

  tab=$(printf '\t')

  {
    printf '%s\n' '---'
    printf '%s\n' 'layout: default'
    printf 'title: "%s PDF Handouts"\n' "$course"
    printf '%s\n' '---'
    printf '\n# %s PDF Handouts\n\n' "$course"
    printf 'Printable slide handouts for %s.\n\n' "$course"
    printf '| Deck | PDF |\n'
    printf '| --- | --- |\n'

    sort -t "$tab" -k2,2 -k4,4 "$manifest" | awk -F '\t' -v course="$course" '
      $1 == course {
        printf("| %s | [Open](%s) |\n", $7, $8)
      }
    '
  } > "$index_file"
}

stage_dir=$(mktemp -d "${RUNNER_TEMP:-/tmp}/slides-sync.XXXXXX")
trap 'rm -rf "$stage_dir"' EXIT

publish_root="$stage_dir/slides"
mkdir -p "$publish_root"

if [ -d "$target_repo/slides" ]; then
  rsync -a "$target_repo/slides/" "$publish_root/"
fi

manifest="$stage_dir/decks.tsv"
: > "$manifest"

active_html="$stage_dir/active-html.tsv"
active_pdf="$stage_dir/active-pdf.tsv"
active_files="$stage_dir/active-files.tsv"
: > "$active_html"
: > "$active_pdf"
: > "$active_files"

docs=()
shopt -s nullglob
while IFS= read -r -d '' doc; do
  docs+=("$doc")
# Only top-level slide decks are published. Nested .qmd files belong to
# supporting material, extensions, or in-progress content.
done < <(find "$source_dir" -maxdepth 1 -type f -name '*.qmd' -print0)

echo "Publishing full slide site from rendered outputs"

prune_legacy_root_outputs "$publish_root"

# Quarto's Reveal.js support files include package README files. Jekyll treats
# them as pages and adds their titles (for example, Chalkboard) to the global
# site navigation; they are not required by the rendered decks. Remove them
# from all existing course outputs as well as newly copied decks.
find "$publish_root" -type f -path '*_files/*.md' -delete

for doc in "${docs[@]}"; do
  base=$(basename "$doc" .qmd)
  course=$(extract_yaml_scalar course "$doc")
  title=$(extract_yaml_scalar title "$doc")
  chapter=$(extract_yaml_scalar chapter "$doc")
  draft_state=$(extract_yaml_scalar draft_state "$doc")

  if [ -z "${course:-}" ]; then
    course="${SLIDES_COURSE_CODE:-CST334}"
  fi
  if [ -z "${title:-}" ]; then
    title="$base"
  fi
  if [ -n "${chapter:-}" ]; then
    deck_label="$chapter - $title"
  else
    deck_label="$title"
  fi
  pdf_name="$(sanitize_path_component "$deck_label").pdf"
  if [ -z "${draft_state:-}" ]; then
    draft_state="final"
  fi
  if [ "$draft_state" = "alpha" ]; then
    continue
  fi

  rendered=false
  if [ "${#rendered_docs[@]}" -eq 0 ] || is_rendered_doc "$base"; then
    rendered=true
  fi

  course_dir="$publish_root/$course"
  mkdir -p "$course_dir"
  mkdir -p "$course_dir/assets"
  mkdir -p "$course_dir/pdfs"

  if [ "$rendered" = "true" ]; then
    if [ ! -f "$build_dir/$base.html" ]; then
      echo "Missing rendered HTML for $doc" >&2
      exit 1
    fi
    if [ ! -f "$build_dir/pdfs/$course/$base.pdf" ]; then
      echo "Missing rendered PDF for $doc" >&2
      exit 1
    fi
  fi

  if [ "$rendered" = "true" ]; then
    copy_file "$build_dir/$base.html" "$course_dir/$base.html"
    copy_file "$build_dir/pdfs/$course/$base.pdf" "$course_dir/pdfs/$pdf_name"
    copy_file "$build_dir/styles.css" "$course_dir/styles.css"
    copy_dir "$build_dir/${base}_files" "$course_dir/${base}_files"
    find "$course_dir/${base}_files" -type f -name '*.md' -delete
    copy_dir "$build_dir/assets" "$course_dir/assets"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$course" "$base" "$doc" "$title" "$draft_state" "$chapter" "$deck_label" "$pdf_name" >> "$manifest"
  printf '%s\n' "$course_dir/$base.html" >> "$active_html"
  printf '%s\n' "$course_dir/pdfs/$pdf_name" >> "$active_pdf"
  printf '%s\n' "$course_dir/${base}_files" >> "$active_files"
done

prune_stale_paths() {
  local manifest_file="$1"
  local kind="$2"
  local root="$3"

  find "$root" -type f -name "$kind" -print0 | while IFS= read -r -d '' file; do
    if ! grep -Fxq "$file" "$manifest_file"; then
      rm -f "$file"
    fi
  done
}

# A source repository owns only its own course directory. Do not prune decks
# published by other course repositories during an incremental sync.
while IFS= read -r course; do
  course_dir="$publish_root/$course"
  prune_stale_paths "$active_html" '*.html' "$course_dir"
  find "$course_dir" -type f -path '*/pdfs/*.pdf' -print0 | while IFS= read -r -d '' file; do
    if ! grep -Fxq "$file" "$active_pdf"; then
      rm -f "$file"
    fi
  done
  find "$course_dir" -type d -name '*_files' -print0 | while IFS= read -r -d '' dir; do
    if ! grep -Fxq "$dir" "$active_files"; then
      rm -rf "$dir"
    fi
  done
done < <(awk -F '\t' '!seen[$1]++ { print $1 }' "$manifest")

for file in "$build_dir"/*; do
  [ -e "$file" ] || continue
  name=$(basename "$file")

  case "$name" in
    *.html|*_files|assets)
      continue
      ;;
  esac

  if [ -f "$file" ]; then
    for course_dir in "$publish_root"/*; do
      [ -d "$course_dir" ] || continue
      copy_file "$file" "$course_dir/$name"
    done
  fi
done

awk -F '\t' '
  {
    if (!seen[$1]++) {
      courses[++count] = $1
    }
  }
  END {
    for (i = 1; i <= count; i++) {
      print courses[i]
    }
  }
' "$manifest" | while IFS= read -r course; do
  write_course_pdf_index "$publish_root" "$course" "$manifest"
done

if [ ! -s "$manifest" ]; then
  echo "No slide decks found" >&2
  exit 0
fi

awk -F '\t' '
  {
    if (!seen[$1]++) {
      courses[++count] = $1
    }
  }
  END {
    for (i = 1; i <= count; i++) {
      print courses[i]
    }
  }
' "$manifest" | while IFS= read -r course; do
  write_course_index "$publish_root" "$course" "$manifest"
done

write_root_index "$publish_root"

mkdir -p "$target_repo/slides"
rsync -a --delete "$publish_root/" "$target_repo/slides/"

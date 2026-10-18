#!/usr/bin/env bash
# Read-only disk usage report, aimed at macOS (also runs on Linux).
# Deletes nothing - it only measures.
#
#   bash disk-space/report.sh             # saves to ~/disk-report-<timestamp>.txt
#   bash disk-space/report.sh out.txt
#
# Written for the bash 3.2 that ships with macOS.

set -u

OUT="${1:-$HOME/disk-report-$(date +%Y%m%d-%H%M%S).txt}"
OS="$(uname -s)"
MIN_KB=51200        # hide anything under 50 MB
DRILL_KB=1048576    # break down folders of 1 GB or more
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

note() { printf '%s\n' "$*" >&2; }
section() { printf '\n== %s ==\n' "$1"; }

human() {
  awk -v k="$1" 'BEGIN {
    split("K M G T", u, " "); i = 1
    while (k >= 1024 && i < 4) { k /= 1024; i++ }
    fmt = i < 3 ? "%.0f%s" : "%.1f%s"
    printf fmt, k, u[i]
  }'
}

# Shorten paths under $HOME to ~/...
tilde() {
  case "$1" in
    "$HOME"/*) printf '~%s' "${1#"$HOME"}" ;;
    *) printf '%s' "$1" ;;
  esac
}

mdate() {
  if [ "$OS" = Darwin ]; then
    stat -f %Sm -t %Y-%m-%d "$1"
  else
    date -r "$1" +%Y-%m-%d
  fi 2>/dev/null
}

# "<kb>\t<path>" for each of the given paths that exists.
sizes() {
  for p in "$@"; do
    [ -e "$p" ] && du -skx "$p" 2>/dev/null
  done
}

# Read "<kb>\t<path>" lines; print the largest $1 that are at least MIN_KB.
table() {
  sort -rn | head -n "$1" | while IFS=$'\t' read -r kb path; do
    [ "$kb" -ge "$MIN_KB" ] && printf '  %7s  %s\n' "$(human "$kb")" "$(tilde "$path")"
  done
}

# Print the children of $1 from home.du, largest first, indented by depth.
# Recurse into children of DRILL_KB or more, down to depth 3.
tree() {
  local dir="$1" indent="$2" depth="$3" kb path
  D="$dir/" awk -F'\t' '
    index($2, ENVIRON["D"]) == 1 && index(substr($2, length(ENVIRON["D"]) + 1), "/") == 0
  ' "$TMP/home.du" | sort -rn | head -n 12 > "$TMP/tree.$depth"
  while IFS=$'\t' read -r kb path; do
    [ "$kb" -ge "$MIN_KB" ] || continue
    printf '  %7s  %s%s\n' "$(human "$kb")" "$indent" "${path##*/}"
    if [ "$depth" -lt 3 ] && [ "$kb" -ge "$DRILL_KB" ]; then
      tree "$path" "$indent    " $((depth + 1))
    fi
  done < "$TMP/tree.$depth"
}

# Well-known big folders: "<path under ~ or absolute>|<what it is: how to clear it>".
known_hogs() {
  cat <<'EOF'
.Trash|Trash: empty it in Finder
.local/share/Trash|Trash
Library/Caches|App caches: apps rebuild them
Library/Logs|App logs
Library/Developer/Xcode/DerivedData|Xcode build cache: safe to delete
Library/Developer/Xcode/Archives|Old Xcode app archives
Library/Developer/Xcode/iOS DeviceSupport|Xcode device symbols: re-downloaded when needed
Library/Developer/CoreSimulator/Devices|iOS simulators: `xcrun simctl delete unavailable`
Library/Developer/CoreSimulator/Caches|Simulator caches: safe to delete
/Library/Developer/CoreSimulator|Simulator runtimes: Xcode > Settings > Platforms
Library/Application Support/MobileSync/Backup|iPhone/iPad backups: Finder > your device > Manage Backups
Library/Containers/com.docker.docker|Docker Desktop disk: `docker system prune`
Library/Messages/Attachments|iMessage attachments: Messages > Settings > Keep messages
Library/Mail|Mail storage
Library/Android/sdk|Android SDK
.android/avd|Android emulator images
.npm|npm cache: `npm cache clean --force`
.yarn/berry/cache|Yarn cache: `yarn cache clean`
Library/pnpm/store|pnpm store: `pnpm store prune`
.local/share/pnpm/store|pnpm store: `pnpm store prune`
.bun/install/cache|Bun cache: `bun pm cache rm`
.cache|Tool caches (pip, Hugging Face, Playwright, ...)
.gradle/caches|Gradle cache
.m2/repository|Maven artifacts
.cargo/registry|Cargo download cache
.rustup/toolchains|Rust toolchains: `rustup toolchain list`
go/pkg/mod|Go module cache: `go clean -modcache`
.pyenv/versions|pyenv Python versions: `pyenv versions`
.nvm/versions|nvm Node versions: `nvm ls`
.conda/pkgs|conda package cache: `conda clean --all`
miniconda3/pkgs|conda package cache: `conda clean --all`
anaconda3/pkgs|conda package cache: `conda clean --all`
opt/miniconda3/pkgs|conda package cache: `conda clean --all`
opt/anaconda3/pkgs|conda package cache: `conda clean --all`
.ollama/models|Ollama models: `ollama list`, `ollama rm <model>`
.lmstudio/models|LM Studio models
Downloads|Downloads folder
Pictures/Photos Library.photoslibrary|Photos: Settings > iCloud > Optimize Mac Storage
/Library/Application Support/GarageBand|GarageBand sound library
/Library/Application Support/Logic|Logic sound library
EOF
}

report() {
  printf 'Disk report, %s' "$(date '+%Y-%m-%d %H:%M')"
  [ "$OS" = Darwin ] && printf ', macOS %s' "$(sw_vers -productVersion 2>/dev/null)"
  printf '\nRead-only: nothing was deleted. Sizes under 50 MB are hidden.\n'

  section "Disk"
  if [ "$OS" = Darwin ]; then
    df -h / /System/Volumes/Data 2>/dev/null
  else
    df -h "$HOME"
  fi
  if command -v tmutil >/dev/null 2>&1; then
    printf 'Time Machine local snapshots: %s\n' \
      "$(tmutil listlocalsnapshots / 2>/dev/null | grep -c 'com.apple')"
  fi

  note "Measuring your home folder (the slow part, can take a few minutes)..."
  du -kx -d 3 "$HOME" 2>/dev/null > "$TMP/home.du"
  section "Home folder: $(human "$(H="$HOME" awk -F'\t' '$2 == ENVIRON["H"] { print $1 }' "$TMP/home.du")")"
  printf '(folders of 1 GB+ are broken down, 3 levels deep)\n'
  tree "$HOME" "" 1

  note "Checking known space hogs..."
  section "Known space hogs, with how to clear them"
  known_hogs | while IFS='|' read -r rel what; do
    case "$rel" in /*) p="$rel" ;; *) p="$HOME/$rel" ;; esac
    [ -e "$p" ] || continue
    kb=$(du -skx "$p" 2>/dev/null | cut -f1)
    [ -n "$kb" ] && [ "$kb" -ge "$MIN_KB" ] && printf '%s\t%s\t%s\n' "$kb" "$p" "$what"
  done | sort -rn | while IFS=$'\t' read -r kb p what; do
    printf '  %7s  %-50s %s\n' "$(human "$kb")" "$(tilde "$p")" "$what"
  done

  note "Looking for project build folders..."
  section "Project build folders (node_modules, virtualenvs, ...): rebuilt by reinstalling"
  find "$HOME" -xdev \( -path "$HOME/Library" -o -path "$HOME/.*" \) -prune -o -type d \( \
      -name node_modules -o -name .venv -o -name venv -o -name .next -o -name .tox \
      -o -name .terraform -o -name Pods -o -name .gradle \
      -o \( -name target -exec test -f {}/../Cargo.toml \; \) \
    \) -prune -print 2>/dev/null |
    while IFS= read -r d; do du -skx "$d" 2>/dev/null; done > "$TMP/builds.du"
  printf '%s folders, %s total\n' "$(wc -l < "$TMP/builds.du" | tr -d ' ')" \
    "$(human "$(awk -F'\t' '{ s += $1 } END { print s + 0 }' "$TMP/builds.du")")"
  [ -s "$TMP/builds.du" ] && printf '  %7s  %-10s  %s\n' size modified path
  sort -rn "$TMP/builds.du" | head -n 30 | while IFS=$'\t' read -r kb path; do
    [ "$kb" -ge "$MIN_KB" ] &&
      printf '  %7s  %-10s  %s\n' "$(human "$kb")" "$(mdate "$path")" "$(tilde "$path")"
  done

  note "Looking for files over 500 MB..."
  section "Files over 500 MB"
  find "$HOME" -xdev -type f -size +512000k -exec du -k {} + 2>/dev/null | table 30

  if [ "$OS" = Darwin ]; then
    section "Applications"
    sizes /Applications/* "$HOME"/Applications/* | table 20
  fi

  if command -v brew >/dev/null 2>&1; then
    note "Asking Homebrew what it could clean..."
    section "Homebrew"
    freed=$(HOMEBREW_NO_AUTO_UPDATE=1 brew cleanup --dry-run 2>/dev/null | grep -i 'would free')
    printf '  %s\n' "${freed:-Nothing for brew cleanup to remove.}"
  fi

  if command -v docker >/dev/null 2>&1; then
    section "Docker"
    if dock=$(docker system df 2>/dev/null); then
      printf '%s\n' "$dock"
    else
      printf "  Docker isn't running, so its images and volumes weren't measured.\n"
    fi
  fi
}

note "Read-only scan; nothing will be deleted."
note "macOS may ask whether Terminal can access some folders. Allowing gives a fuller report."
report | tee "$OUT"
note ""
note "Saved to $OUT"

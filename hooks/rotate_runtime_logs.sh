#!/bin/bash
# rotate_runtime_logs.sh - size-based copytruncate rotation for runtime *.log
# files written by launchd jobs (StandardOutPath/StandardErrorPath).
#
# Why copytruncate: the launchd jobs keep their log open for their whole
# lifetime, so a rename would leave them writing into the archived inode. A
# copy followed by an in-place truncate keeps the current path (and the
# writer's descriptor) valid, at the cost stated under "Semantics" below.
#
# Usage:
#   rotate_runtime_logs.sh [--dry-run] [DIR ...]
#     DIR defaults to $AGENTSTACK_RUNTIME_DIR, then ~/.agentstack/runtime.
#     Only regular files matching DIR/*.log (depth 1) are candidates.
#
# Environment:
#   AGENTSTACK_LOG_ROTATE_THRESHOLD_BYTES  rotate when size >= this (50 MiB)
#   AGENTSTACK_LOG_ROTATE_KEEP             archives to keep, NAME.log.1..N (3)
#   AGENTSTACK_LOG_ROTATE_LOCK_DIR         mkdir lock shared by all runs
#   AGENTSTACK_LOG_ROTATE_ARCHIVE_DIR      where the oldest archive goes before
#                                          its slot is reused (see "Semantics")
#
# Semantics (read before deploying):
#   * Threshold is checked once per run. Nothing rotates between runs, so a
#     file can overshoot the threshold by one interval's growth (daily cadence
#     × the measured ~110 KiB/min of mail-watcher.log ≈ +150 MiB/day).
#   * copytruncate is NOT lossless: bytes appended between the end of `cp`
#     and the truncate are dropped. launchd opens StandardOutPath with
#     O_APPEND, so after the truncate the writer continues at the new end of
#     file; a writer that opened without O_APPEND would instead leave a sparse
#     hole of NUL bytes up to its old offset.
#   * Archives are plain copies: NAME.log.1 is the newest, NAME.log.KEEP the
#     oldest. Logs are records and are never deleted (storage v5.9, head
#     2026-10-14 mail 24844): before NAME.log.KEEP is overwritten it is
#     gzipped into AGENTSTACK_LOG_ROTATE_ARCHIVE_DIR as
#     NAME.log.KEEP.<UTC>.<sha12>.gz, the gunzip SHA-256 is checked against
#     the slot, and a tombstone line is appended to tombstones.jsonl there.
#     Only then is the slot removed. If the archive dir is unset, missing or a
#     symlink, or any step fails, that file is not rotated at all.
#   * Symlinks (file or parent directory), paths that resolve outside DIR,
#     and anything not ending in ".log" are skipped and reported.
#   * Every archive slot (NAME.log.1..KEEP) is inspected before anything is
#     changed: a symlink, directory, or multiply-linked file in any slot skips
#     the whole file, so nothing outside DIR can be written or replaced. The
#     copy goes to a fresh mktemp file in DIR and is renamed into place.
#   * A mkdir lock makes concurrent runs exit 0 without rotating. There is no
#     automatic stale-lock recovery: any existing lock, dead pid or not, fails
#     closed with a message, and removing it is a manual step. Release only
#     unlinks this run's own pid file (after checking the lock is not a
#     symlink and the pid is ours) and rmdir's the directory; foreign content
#     is never moved or deleted.
#
# Exit codes: 0 ok (including "nothing to do" and "already running"),
#             2 usage error, 3 a directory argument is unusable.

set -euo pipefail

THRESHOLD="${AGENTSTACK_LOG_ROTATE_THRESHOLD_BYTES:-52428800}"
KEEP="${AGENTSTACK_LOG_ROTATE_KEEP:-3}"
LOCK_DIR="${AGENTSTACK_LOG_ROTATE_LOCK_DIR:-${TMPDIR:-/tmp}/orrery-runtime-log-rotate.lock}"
ARCHIVE_DIR="${AGENTSTACK_LOG_ROTATE_ARCHIVE_DIR:-}"
DRY_RUN=0
LOCK_HELD=0

log() { echo "[log-rotate $(date '+%Y-%m-%dT%H:%M:%S')] $*"; }

usage() {
    echo "usage: $0 [--dry-run] [DIR ...]" >&2
    exit 2
}

file_size() {
    # GNU stat first: on Linux `stat -f` "succeeds" with filesystem data, so
    # the BSD form must be the fallback, not the first attempt.
    stat -c %s "$1" 2>/dev/null || stat -f %z "$1"
}

link_count() {
    stat -c %h "$1" 2>/dev/null || stat -f %l "$1"
}

resolve_path() {
    # Physical path with symlinks resolved. `pwd -P` exists on bash 3.2 and
    # needs no realpath(1), which macOS did not ship until 13.
    local dir
    local base
    dir=$(dirname "$1")
    base=$(basename "$1")
    (cd "$dir" 2>/dev/null && printf '%s/%s\n' "$(pwd -P)" "$base")
}

acquire_lock() {
    # mkdir is the only atomic step; there is deliberately no stale-lock
    # recovery. A rename-based reclaim lets a slow second contender rename the
    # first one's fresh lock away and both run, so an existing lock always
    # fails closed: report it and exit 0. Removing a dead lock is a manual,
    # head-owned operation (check the pid inside, then rm pid + rmdir).
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        printf '%s\n' "$$" > "$LOCK_DIR/pid"
        LOCK_HELD=1
        return 0
    fi
    local lock_pid=""
    [ -f "$LOCK_DIR/pid" ] && [ ! -L "$LOCK_DIR/pid" ] && lock_pid=$(<"$LOCK_DIR/pid")
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
        log "another rotation is running (pid $lock_pid); exiting"
    else
        log "lock $LOCK_DIR exists (pid '${lock_pid}' not running); refusing to rotate — remove it by hand after checking"
    fi
    exit 0
}

release_lock() {
    # Only our own lock: not a symlink, and the pid file carries this pid.
    [ "$LOCK_HELD" -eq 1 ] || return 0
    if [ -L "$LOCK_DIR" ] || [ ! -d "$LOCK_DIR" ]; then
        log "lock $LOCK_DIR changed underneath us; not touching it"
        return 0
    fi
    local owner=""
    [ -f "$LOCK_DIR/pid" ] && [ ! -L "$LOCK_DIR/pid" ] && owner=$(<"$LOCK_DIR/pid")
    if [ "$owner" != "$$" ]; then
        log "lock $LOCK_DIR is owned by pid '${owner}', not $$; leaving it"
        return 0
    fi
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || log "lock $LOCK_DIR not empty after release; left in place"
}

# archive_slot_unsafe PATH: true when PATH exists as anything other than a
# plain, singly-linked regular file (or does not exist at all).
archive_slot_unsafe() {
    local slot="$1"
    if [ -L "$slot" ]; then return 0; fi
    if [ ! -e "$slot" ]; then return 1; fi
    if [ ! -f "$slot" ]; then return 0; fi
    if [ "$(link_count "$slot")" -gt 1 ]; then return 0; fi
    return 1
}

sha256_of() {
    shasum -a 256 "$1" | cut -d' ' -f1
}

archive_dir_usable() {
    [ -n "$ARCHIVE_DIR" ] && [ -d "$ARCHIVE_DIR" ] && [ ! -L "$ARCHIVE_DIR" ]
}

# archive_oldest SLOT NAME: gzip SLOT into ARCHIVE_DIR, verify the restored
# SHA-256, write a tombstone line, then remove SLOT. Any failure leaves SLOT
# in place and returns 1 so the caller does not rotate.
archive_oldest() {
    local slot="$1"
    local name="$2"
    archive_dir_usable || { log "skip $name: $name.$KEEP would be dropped and no usable AGENTSTACK_LOG_ROTATE_ARCHIVE_DIR is set"; return 1; }
    local bytes sha stamp dest tmpgz restored gzsha
    bytes=$(file_size "$slot")
    sha=$(sha256_of "$slot")
    stamp=$(date -u '+%Y%m%dT%H%M%SZ')
    dest="$ARCHIVE_DIR/$(basename "$slot").$stamp.${sha:0:12}.gz"
    if [ -e "$dest" ] || [ -L "$dest" ]; then
        log "skip $name: archive target $dest already exists"; return 1
    fi
    tmpgz=$(mktemp "$ARCHIVE_DIR/.$name.archive.XXXXXX") || { log "skip $name: mktemp in archive dir failed"; return 1; }
    if ! gzip -6 -c "$slot" > "$tmpgz"; then
        rm -f "$tmpgz"; log "skip $name: gzip of $name.$KEEP failed"; return 1
    fi
    restored=$(gunzip -c "$tmpgz" | shasum -a 256 | cut -d' ' -f1)
    if [ "$restored" != "$sha" ]; then
        rm -f "$tmpgz"; log "skip $name: restored SHA $restored != $sha"; return 1
    fi
    mv -f "$tmpgz" "$dest"
    gzsha=$(sha256_of "$dest")
    printf '{"utc":"%s","path":"%s","bytes":%s,"sha256":"%s","class":"runtime-log-archive","kept_copy":"%s","kept_copy_sha256":"%s","reason":"rotate_runtime_logs.sh: oldest slot archived before reuse"}\n' \
        "$stamp" "$slot" "$bytes" "$sha" "$dest" "$gzsha" >> "$ARCHIVE_DIR/tombstones.jsonl"
    rm -f "$slot"
    log "archived $name.$KEEP (${bytes} bytes, sha256 $sha) -> $dest"
    return 0
}

rotate_one() {
    local file="$1"
    local root="$2"
    local name
    name=$(basename "$file")

    if [ -L "$file" ] || [ ! -f "$file" ]; then
        log "skip $name: not a regular file (symlink?)"
        return 0
    fi
    case "$name" in
        *.log) ;;
        *) log "skip $name: not a .log file"; return 0 ;;
    esac
    local real
    real=$(resolve_path "$file")
    case "$real" in
        "$root"/*) ;;
        *) log "skip $name: resolves outside $root ($real)"; return 0 ;;
    esac
    case "${real#"$root"/}" in
        */*) log "skip $name: resolves below a subdirectory of $root"; return 0 ;;
    esac

    local size
    size=$(file_size "$file")
    if [ "$size" -lt "$THRESHOLD" ]; then
        return 0
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        if [ -e "$file.$KEEP" ]; then
            if archive_dir_usable; then
                log "would archive $name.$KEEP to $ARCHIVE_DIR (gzip, SHA-verified; deleted without archive: 0)"
            else
                log "would skip $name: $name.$KEEP has no usable archive dir (deleted without archive: 0)"
                return 0
            fi
        fi
        log "would rotate $name (${size} bytes >= ${THRESHOLD})"
        return 0
    fi

    # Inspect every archive slot before touching anything, so a symlink,
    # directory or hard link planted in any slot cannot redirect a write.
    local i=1
    while [ "$i" -le "$KEEP" ]; do
        if archive_slot_unsafe "$file.$i"; then
            log "skip $name: archive slot $name.$i is not a plain file"
            return 0
        fi
        i=$((i + 1))
    done
    if [ "$(link_count "$file")" -gt 1 ]; then
        log "skip $name: has $(link_count "$file") hard links"
        return 0
    fi

    # Copy first into a fresh, uniquely named file in DIR (never a fixed
    # ".tmp" name that could pre-exist as a link), then shift the slots and
    # rename the copy into slot 1. Only after the copy is in place is the
    # current file truncated.
    local tmp
    if [ -e "$file.$KEEP" ]; then
        archive_oldest "$file.$KEEP" "$name" || return 0
    fi
    tmp=$(mktemp "$root/.$name.rotate.XXXXXX") || { log "skip $name: mktemp failed"; return 0; }
    if ! cp -p "$file" "$tmp"; then
        rm -f "$tmp"
        log "skip $name: copy failed"
        return 0
    fi
    i=$KEEP
    while [ "$i" -gt 1 ]; do
        if [ -f "$file.$((i - 1))" ]; then
            mv -f "$file.$((i - 1))" "$file.$i"
        fi
        i=$((i - 1))
    done
    mv -f "$tmp" "$file.1"
    # copytruncate: the writer keeps its descriptor; see "Semantics" above for
    # the window between the copy and the truncate.
    : > "$file"
    log "rotated $name (${size} bytes) -> $name.1 (keep $KEEP)"
}

main() {
    local dirs=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run) DRY_RUN=1 ;;
            -h|--help) usage ;;
            --) shift; break ;;
            -*) usage ;;
            *) dirs+=("$1") ;;
        esac
        shift
    done
    while [ $# -gt 0 ]; do dirs+=("$1"); shift; done
    if [ "${#dirs[@]}" -eq 0 ]; then
        dirs=("${AGENTSTACK_RUNTIME_DIR:-$HOME/.agentstack/runtime}")
    fi
    case "$THRESHOLD$KEEP" in
        *[!0-9]*) echo "threshold/keep must be integers" >&2; exit 2 ;;
    esac
    if [ "$KEEP" -lt 1 ]; then
        echo "AGENTSTACK_LOG_ROTATE_KEEP must be >= 1" >&2
        exit 2
    fi

    acquire_lock
    trap release_lock EXIT

    local dir
    local root
    local file
    for dir in "${dirs[@]}"; do
        if [ -L "$dir" ] || [ ! -d "$dir" ]; then
            log "directory $dir is missing or a symlink; refusing"
            exit 3
        fi
        root=$(cd "$dir" && pwd -P)
        # depth 1 only; subdirectories (audit/, codex-app/, ...) have their own owners.
        while IFS= read -r file; do
            rotate_one "$file" "$root"
        done < <(find "$root" -maxdepth 1 -name '*.log' -type f 2>/dev/null | LC_ALL=C sort)
    done
}

main "$@"

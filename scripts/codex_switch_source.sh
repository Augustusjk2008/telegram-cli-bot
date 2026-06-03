#!/usr/bin/env bash
# Switch codex source
set -euo pipefail

CODEX_DIR="${HOME}/.codex"
BACKUP_DIR="${CODEX_DIR}/backup"
STATE_FILE="${CODEX_DIR}/.switch_state"

clear_files() {
  local del_ok=1

  if [[ -f "${CODEX_DIR}/auth.json" ]]; then
    if rm -f -- "${CODEX_DIR}/auth.json"; then
      echo "Deleted auth.json"
    else
      echo "Error: Failed to delete auth.json"
      del_ok=0
    fi
  else
    echo "auth.json not found, skipped"
  fi

  if [[ -f "${CODEX_DIR}/config.toml" ]]; then
    if rm -f -- "${CODEX_DIR}/config.toml"; then
      echo "Deleted config.toml"
    else
      echo "Error: Failed to delete config.toml"
      del_ok=0
    fi
  else
    echo "config.toml not found, skipped"
  fi

  rm -f -- "${STATE_FILE}"

  if [[ "${del_ok}" -eq 0 ]]; then
    echo "Clear aborted due to errors."
    exit 1
  fi

  echo "Clear complete."
}

if [[ ! -d "${CODEX_DIR}" ]]; then
  echo "Error: Codex directory does not exist."
  exit 1
fi

if [[ "${1:-}" == "clear" ]]; then
  clear_files
  exit 0
fi

if [[ ! -d "${BACKUP_DIR}" ]]; then
  echo "Error: Backup directory does not exist."
  exit 1
fi

mapfile -t folders < <(find "${BACKUP_DIR}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
folder_count="${#folders[@]}"

if [[ "${folder_count}" -eq 0 ]]; then
  echo "Error: No subfolders found in backup directory."
  exit 1
fi

current_index=0
if [[ -f "${STATE_FILE}" ]]; then
  current_index="$(head -n 1 "${STATE_FILE}" | tr -dc '0-9' || true)"
  current_index="${current_index:-0}"
fi

next_index=$((current_index + 1))
if [[ "${next_index}" -gt "${folder_count}" ]]; then
  next_index=1
fi
if [[ "${next_index}" -lt 1 ]]; then
  next_index=1
fi

target_folder="${folders[$((next_index - 1))]}"
target_dir="${BACKUP_DIR}/${target_folder}"

echo "Backup folders found: ${folder_count}"
echo "Current index: ${current_index}"
echo "Switching to folder ${next_index}: ${target_folder}"

copy_ok=1

for file_name in auth.json config.toml; do
  src_file="${target_dir}/${file_name}"
  dst_file="${CODEX_DIR}/${file_name}"
  if [[ -f "${src_file}" ]]; then
    if cp -f -- "${src_file}" "${dst_file}"; then
      echo "Copied ${file_name} from ${target_folder}"
    else
      echo "Error: Failed to copy ${file_name}"
      copy_ok=0
    fi
  else
    echo "Warning: ${file_name} not found in ${target_folder}"
  fi
done

if [[ "${copy_ok}" -eq 0 ]]; then
  echo "Switch aborted due to copy errors."
  exit 1
fi

printf '%s\n' "${next_index}" > "${STATE_FILE}"
echo "Switch complete. Active folder: ${target_folder}"

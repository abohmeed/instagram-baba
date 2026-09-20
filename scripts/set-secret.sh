#!/bin/zsh
# Write a credential into .env without it appearing on screen, in shell
# history, or in any transcript.
#
#   ./scripts/set-secret.sh META_APP_SECRET            # reads the clipboard
#   ./scripts/set-secret.sh META_APP_SECRET --prompt   # types it in, hidden
#
# The clipboard form is the useful one when you have just copied a value out
# of a web console: nothing is typed and nothing is echoed. Non-interactive
# shells cannot prompt, so the clipboard is the default.
set -eu

NAME="${1:-}"
MODE="${2:-clipboard}"
if [ -z "$NAME" ]; then
  echo "usage: $0 <SECRET_NAME> [--prompt]" >&2
  echo "   e.g. $0 META_APP_SECRET" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [ "$MODE" = "--prompt" ]; then
  if [ ! -t 0 ]; then
    echo "error: --prompt needs an interactive terminal; omit it to use the clipboard" >&2
    exit 2
  fi
  printf 'Paste value for %s (hidden): ' "$NAME" >&2
  stty -echo; IFS= read -r VALUE; stty echo; printf '\n' >&2
else
  command -v pbpaste >/dev/null 2>&1 || { echo "error: pbpaste not found" >&2; exit 2; }
  VALUE="$(pbpaste | tr -d '[:space:]')"
fi

if [ -z "$VALUE" ]; then
  echo "nothing to write; .env unchanged" >&2
  exit 1
fi
# Both input paths strip surrounding whitespace; a value with an interior
# space is a paste accident, not a credential.
VALUE="$(printf '%s' "$VALUE" | tr -d '[:space:]')"
if [ -z "$VALUE" ]; then
  echo "value was only whitespace; .env unchanged" >&2
  exit 1
fi

touch "$ENV_FILE"
TMP="$(mktemp)"
grep -v "^${NAME}=" "$ENV_FILE" > "$TMP" 2>/dev/null || true
printf '%s=%s\n' "$NAME" "$VALUE" >> "$TMP"
sort -o "$TMP" "$TMP"
mv "$TMP" "$ENV_FILE"
chmod 600 "$ENV_FILE"

FP="$(printf '%s' "$VALUE" | shasum -a 256 | cut -c1-12)"
echo "$NAME updated in .env (${#VALUE} characters, sha256 $FP)" >&2
echo "clipboard still holds it - clear it with: pbcopy </dev/null" >&2

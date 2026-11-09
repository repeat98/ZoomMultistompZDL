#!/bin/bash
# Double-click this in Finder to open the MS-70CDR Patch Editor.
# Reuses an already-running server instead of starting a second one.
cd "$(dirname "$0")" || exit 1

find_running() {
  for p in $(seq 8000 8019); do
    if curl -sf -o /dev/null "http://127.0.0.1:$p/tools/patch_editor.html"; then
      echo "$p"; return 0
    fi
  done
  return 1
}

if p=$(find_running); then
  echo "Server already running on port $p"
  open "http://localhost:$p/tools/patch_editor.html"
  exit 0
fi

echo "Starting local server..."
python3 tools/serve_editor.py --no-open >/tmp/pe_serve.log 2>&1 &
for _ in $(seq 1 40); do
  if p=$(find_running); then
    open "http://localhost:$p/tools/patch_editor.html"
    echo "Patch Editor -> http://localhost:$p/tools/patch_editor.html"
    echo "Leave this window open. Close it to stop the server."
    wait
    exit 0
  fi
  sleep 0.25
done
echo "Server did not start. Log:"; cat /tmp/pe_serve.log; read -r -n1 -p "Press any key..."

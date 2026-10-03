#!/usr/bin/env bash
# Builds dist/<name>-<version>.zip from the plugin source.
#
# Usage:
#   ./scripts/build-zip.sh
#
# Reads plugin.json for name/version and writes dist/<name>-<version>.zip
# ready for the panel's "Upload Zip" install path. The archive is written
# with Python's zipfile (every dev box has it; the zip binary is not part of
# Git Bash on Windows), staging nothing and excluding dev junk (.git,
# node_modules, caches, the release zips themselves).

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f plugin.json ]]; then
    echo "plugin.json not found in $(pwd)" >&2
    exit 1
fi

PYTHON="$(command -v python3 || command -v python)"

"$PYTHON" - <<'PY'
import json
import os
import zipfile

with open('plugin.json', encoding='utf-8') as handle:
    manifest = json.load(handle)
name = manifest['name']
version = manifest['version']

# Directory names excluded at any depth. Note: NOT 'dist' — frontend/dist/
# carries the prebuilt runtime bundle the panel loads (frontend_entry), so
# only the TOP-LEVEL dist/ (the release zips) is skipped.
EXCLUDE_DIRS = {
    '.git', '.github', 'node_modules', '__pycache__', '.venv', 'venv',
    'build', '.pytest_cache', '.idea', '.vscode', 'scripts',
}
EXCLUDE_EXT = {'.pyc', '.pyo', '.log'}

zip_path = os.path.join('dist', f'{name}-{version}.zip')
os.makedirs('dist', exist_ok=True)
if os.path.exists(zip_path):
    os.remove(zip_path)

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs
                   if d not in EXCLUDE_DIRS and not (d == 'dist' and root == '.')]
        for filename in files:
            if os.path.splitext(filename)[1].lower() in EXCLUDE_EXT:
                continue
            full = os.path.join(root, filename)
            arcname = os.path.relpath(full, '.')
            archive.write(full, arcname)

size_kb = os.path.getsize(zip_path) // 1024
print(f'Built {zip_path} ({size_kb} KB)'.replace(os.sep, '/'))
print('Upload via panel -> Marketplace -> Plugins -> Upload Zip')
PY

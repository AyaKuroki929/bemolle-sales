#!/bin/bash
# Code.gs をGASへ反映してウェブアプリを更新する（コピペ廃止・2026-09-19）。
# gas/ は clasp の作業フォルダ（.clasp.json に scriptId）。一時置き場に置くと消えるのでリポジトリ内に置く（2026-10-02）
set -e
cd "$(dirname "$0")"
unset NODE_OPTIONS
cp Code.gs gas/コード.js && node --check gas/コード.js
cd gas
clasp push -f >/dev/null
clasp deploy --deploymentId AKfycbw5r9qSAxC613fnqJOdlRsj1ORblpDGGf_IhuYPmJZwfk4kfOGqBxJ4D-OWBicezim7 --description "${1:-update}" | tail -1

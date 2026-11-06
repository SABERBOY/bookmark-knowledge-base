#!/usr/bin/env bash
OUT=/workspace/bookmark-db/content_chunk3.zip
FLAG=/workspace/bookmark-db/content_chunk3.zip.READY
while true; do
  if [[ -f "$OUT" ]]; then
    s1=$(stat -c%s "$OUT" 2>/dev/null || echo 0)
    sleep 5
    s2=$(stat -c%s "$OUT" 2>/dev/null || echo 0)
    if [[ "$s1" == "$s2" && "$s1" -gt 1000 ]]; then
      echo "$(date '+%F %T %z') zip stable size=$s1" > "$FLAG"
      exit 0
    fi
  fi
  sleep 15
done

#!/bin/bash
# SCCS OS — 数据库备份脚本
# 用法: ./scripts/backup_db.sh [backup_dir]
# 默认备份到 data/backups/$(date +%Y%m%d_%H%M%S)/
set -euo pipefail

BACKUP_DIR="${1:-data/backups/$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$BACKUP_DIR"
echo "Backing up to $BACKUP_DIR"

# SQLite 备份
DB_PATH="data/sccsos.db"
if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "$BACKUP_DIR/sccsos.db"
    sqlite3 "$DB_PATH" ".dump" > "$BACKUP_DIR/sccsos_dump.sql"
    echo "  ✅ SQLite: $(wc -c < "$DB_PATH") bytes → $BACKUP_DIR/"
else
    echo "  ⚠️  SQLite DB not found at $DB_PATH"
fi

# Config backup
CONFIG_PATH="sccsos.yaml"
if [ -f "$CONFIG_PATH" ]; then
    cp "$CONFIG_PATH" "$BACKUP_DIR/"
    echo "  ✅ Config: $CONFIG_PATH"
fi

# Pricing config
PRICING_PATH="config/pricing.json"
if [ -f "$PRICING_PATH" ]; then
    cp "$PRICING_PATH" "$BACKUP_DIR/"
    echo "  ✅ Pricing: $PRICING_PATH"
fi

# 清除超过 30 天的旧备份
find data/backups -maxdepth 1 -type d -mtime +30 -exec rm -rf {} \; 2>/dev/null || true

echo "✅ Backup complete: $BACKUP_DIR"
echo "   Retention: 30 days"

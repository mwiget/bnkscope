#!/bin/bash
set -e

echo "================================================"
echo "bnkscope backend"
echo "================================================"

# Docker volumes are created as root but the container runs as bnkscope (uid
# 1000). Warn rather than fail: an unwritable data dir surfaces as a clear
# SQLite error at startup, which is more useful than a shell error here.
for dir in /app/data /app/keys; do
    if [ -d "$dir" ] && [ ! -w "$dir" ]; then
        echo "Warning: $dir is not writable by the bnkscope user"
        echo "   Run: docker exec -u root bnkscope-backend chown -R bnkscope:bnkscope $dir"
    fi
done

# The schema is created from the ORM models by database.init_database() during
# app startup — there are no migrations to run here any more (Phase 4).

exec "$@"

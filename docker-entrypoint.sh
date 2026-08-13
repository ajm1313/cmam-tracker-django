#!/bin/bash

# Wait for the database to be reachable. Supports either DATABASE_URL
# (Railway/PaaS convention) or individual DB_HOST/DB_PORT env vars
# (falls back to 'db'/3306 for local docker-compose usage).
if [ -n "$DATABASE_URL" ]; then
    read DB_WAIT_HOST DB_WAIT_PORT <<< $(python3 -c "
import urllib.parse as up, os
u = up.urlparse(os.environ['DATABASE_URL'])
print(u.hostname or 'db', u.port or 3306)
")
else
    DB_WAIT_HOST="${DB_HOST:-db}"
    DB_WAIT_PORT="${DB_PORT:-3306}"
fi
echo "Waiting for database at ${DB_WAIT_HOST}:${DB_WAIT_PORT}..."
for i in $(seq 1 30); do
    if nc -z "$DB_WAIT_HOST" "$DB_WAIT_PORT" 2>/dev/null; then
        echo "Database is ready!"
        break
    fi
    sleep 2
done

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Seed default roles
echo "Seeding roles..."
python manage.py seed_roles || true

# Create superuser if it doesn't exist (configurable via env vars)
echo "Creating superuser..."
python manage.py shell -c "
from apps.users.models import User
import os
email = os.environ.get('ADMIN_EMAIL', 'admin@cmam.com')
password = os.environ.get('ADMIN_PASSWORD', 'admin123')
if not User.objects.filter(email=email).exists():
    User.objects.create_superuser(email, password, name='Administrator')
    print(f'Superuser created: {email}')
else:
    print('Superuser already exists')
" || true

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Gunicorn (Railway assigns the port dynamically via \$PORT)
echo "Starting Gunicorn server..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT:-8000} \
    --workers 2 \
    --threads 4 \
    --worker-class sync \
    --timeout 300 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile - \
    --log-level info

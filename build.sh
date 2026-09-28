#!/usr/bin/env bash
# Render runs this on every deploy.
set -o errexit  # Stop at the first failing command.

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Render's free tier has no shell, so the admin account is created from env vars:
# DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_PASSWORD.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python manage.py createsuperuser --no-input || echo "Superuser already exists; skipping."
fi

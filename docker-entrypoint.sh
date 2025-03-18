#!/usr/bin/env sh
umask 0000

set -ex

cd /usr/src/app/

if [ "$HEALTH_CHECK_DATABASE" = "postgres" ]
then
python << END
import psycopg2, sys, time

suggest_unrecoverable_after = 30
start = time.time()

print("POSTGRES Connecting to ${DATABASE_URL}")

while True:
    try:
        psycopg2.connect(dsn="$DATABASE_URL")
        break
    except psycopg2.OperationalError as error:
        sys.stderr.write("Waiting for PostgreSQL to become available...\n")
        if time.time() - start > suggest_unrecoverable_after:
            sys.stderr.write("  This is taking longer than expected. The following exception may be indicative of an unrecoverable error: '{}'\n".format(error))
    time.sleep(1)
END
>&2 echo 'PostgreSQL is available'
fi

if [ "$HEALTH_CHECK_BROKER" = "redis" ]
then
python << END
import redis, sys, time

print("REDIS Connecting to ${CELERY_BROKER_URL}")

suggest_unrecoverable_after = 30
start = time.time()
while True:
    try:
        r = redis.from_url("${CELERY_BROKER_URL}")
        r.ping()
        break
    except redis.exceptions.RedisError as error:
        sys.stderr.write("Waiting for redis to become available...\n")
        if time.time() - start > suggest_unrecoverable_after:
            sys.stderr.write("  This is taking longer than expected. The following exception may be indicative of an unrecoverable error: '{}'\n".format(error))
        time.sleep(1)
END
>&2 echo 'Redis is available'
fi

if [ "$INIT_VIDAR_DATA" = "True" ]
then
  python manage.py migrate --noinput
  python manage.py init_vidar --create-tasks
  python manage.py init_example_users
  #python manage.py collectstatic --noinput &
fi
exec "$@"

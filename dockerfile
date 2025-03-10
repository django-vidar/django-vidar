# pull official base image
FROM python:3.12-slim-bookworm

RUN apt update -y && \
    apt install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

LABEL org.opencontainers.image.source https://github.com/django-vidar/django-vidar

# install dependencies
RUN python -m pip install psycopg2-binary gunicorn whitenoise
COPY ./requirements.txt .
RUN --mount=type=cache,target=/root/.cache pip install -r requirements.txt

# set work directory
WORKDIR /usr/src/app

ARG PUID=1000
ARG PGID=1000

RUN groupadd -f -g ${PGID} abc
RUN adduser --disabled-password --gecos "" --uid ${PUID} --gid ${PGID} abc

RUN chown ${PUID}:${PGID} /usr/src/app /media /tmp

USER abc

# copy project
COPY . .

COPY ./docker-entrypoint.sh .
# RUN chmod +x ./docker-entrypoint.sh
ENTRYPOINT ["sh", "/usr/src/app/docker-entrypoint.sh"]

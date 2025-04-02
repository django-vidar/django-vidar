# pull official base image
FROM python:3.12-alpine

COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

LABEL org.opencontainers.image.source=https://github.com/django-vidar/django-vidar

# install dependencies
COPY ./requirements/core.txt ./requirements/docker.txt .
RUN --mount=type=cache,target=/root/.cache pip install --no-compile -r core.txt -r docker.txt

# set work directory
WORKDIR /usr/src/app

COPY . .

COPY ./docker-entrypoint.sh .
ENTRYPOINT ["sh", "/usr/src/app/docker-entrypoint.sh"]

FROM ghcr.io/ministryofjustice/hmpps-python:python3.13-alpine AS base

USER root
RUN apk add --no-cache git
USER 2000


# dependencies
COPY includes includes
COPY processes processes
COPY utilities utilities

# initialise uv
COPY pyproject.toml .
RUN uv sync

# Copy the Python goodness
COPY ./*.py .

CMD [ "uv", "run", "python", "-u", "github_discovery.py" ]

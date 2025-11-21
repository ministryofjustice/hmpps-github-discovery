FROM ghcr.io/ministryofjustice/hmpps-python:python3.13-alpine AS base

# dependencies
COPY includes includes
COPY processes processes
COPY utilities utilities

# initialise uv
COPY pyproject.toml .
RUN uv sync

# Copy the Python goodness
COPY ./*.py .

# update PATH environment variable
ENV PATH=/home/appuser/.local:$PATH

RUN chown -R 2000:2000 /app

USER 2000

CMD [ "uv", "run", "python", "-u", "github_discovery.py" ]

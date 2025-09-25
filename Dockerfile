FROM ghcr.io/astral-sh/uv:python3.13-alpine
WORKDIR /app

RUN addgroup --gid 2000 --system appgroup && \
    adduser --uid 2000 --system appuser --gid 2000 --home /home/appuser

# dependencies
COPY includes includes
COPY processes processes
COPY utilities utilities

# initialise uv
COPY pyproject.toml .
RUN uv pip install --user

# Copy the Python goodness
COPY ./*.py .


# update PATH environment variable
ENV PATH=/home/appuser/.local:$PATH

USER 2000

CMD [ "uv", "run", "python", "-u", "github_discovery.py" ]

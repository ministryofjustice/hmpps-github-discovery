FROM ghcr.io/astral-sh/uv:python3.13-alpine
WORKDIR /app

RUN addgroup -g 2000 appgroup && \
    adduser -u 2000 -G appgroup -h /home/appuser -D appuser

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

USER 2000

CMD [ "uv", "run", "python", "-u", "github_discovery.py" ]

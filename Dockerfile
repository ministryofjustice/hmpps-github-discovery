FROM python:3.13-alpine AS builder
COPY requirements.txt .

RUN addgroup --gid 2000 --system appgroup && \
    adduser --uid 2000 --system appuser --gid 2000 --home /home/appuser

USER 2000

# install dependencies to the local user directory
RUN pip install --user -r requirements.txt

FROM python:3.13-alpine
WORKDIR /app

RUN addgroup --gid 2000 --system appgroup && \
    adduser --uid 2000 --system appuser --gid 2000 --home /home/appuser

# copy the dependencies from builder stage
COPY --chown=appuser:appgroup --from=builder /home/appuser/.local /home/appuser/.local
COPY includes includes
COPY classes classes
COPY processes processes
COPY utilities utilities
COPY models modules

COPY ./github_discovery.py .
COPY ./github_teams_discovery.py .
COPY ./github_component_discovery.py .
COPY ./requirements.txt .

# update PATH environment variable
ENV PATH=/home/appuser/.local:$PATH

USER 2000

CMD [ "python", "-u", "github_discovery.py" ]

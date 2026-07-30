# Deployment Analytics Pipeline

This project collects deployment analytics from GitHub repositories in the
Service Catalogue and writes month-based reporting datasets to `analytics/`.

## What The Script Does

Running `github_deployment_analytics.py` will:

1. Determine a reporting window.
2. Query Service Catalogue components.
3. Query GitHub for merged PRs and production deployments in the window.
4. Compute service-level metrics and flatten events/reverts into CSVs.
5. Write a manifest with reporting metadata.
6. Optionally upload output files to SharePoint.

The script always emits run metadata (`snapshot_at`/`generated_at`) and period
metadata (`report_month`, `window_start`, `window_end`).

## Reporting Window Behavior

Default behavior is month-first:

- No arguments: runs for the previous calendar month.
- `--month YYYY-MM`: runs for that calendar month.
- Optional advanced mode: `--since` and `--until` can be provided together as
  an ISO 8601 custom window.

Guardrails:

- `--month` cannot be combined with `--since` or `--until`.
- `--since` and `--until` must be provided together.
- `--until` must be later than `--since`.

## Environment Variables

The script reads these environment variables at runtime:

| Variable | Required | Default | Description |
|---|---|---|---|
| `UPLOAD` | No | `false` | If true, uploads generated files to SharePoint. |
| `SITE_NAME` | Only if `UPLOAD=true` | `HMPPSSRE` | SharePoint site name. |
| `DRIVE_NAME` | Only if `UPLOAD=true` | `Documents` | SharePoint drive/library name. |
| `FOLDER_PATH` | Only if `UPLOAD=true` | `analytics/deployments` | Base SharePoint folder path. |
| `PARTITION_BY_DATE` | No | `true` | If true, writes output under `year=YYYY/month=MM`. |

Boolean values accepted by `UPLOAD` and `PARTITION_BY_DATE`:

- `1`, `true`, `yes`, `y`, `on` (case-insensitive) are treated as true.

## Usage

Run using `uv`:

```bash
uv run process_deployments.py
```

Run for a specific month (recommended):

```bash
uv run process_deployments.py --month 2026-06
```

Run a custom window (advanced):

```bash
uv run process_deployments.py \
  --since 2026-06-01T00:00:00Z \
  --until 2026-07-01T00:00:00Z
```

Show CLI help:

```bash
uv run process_deployments.py --help
```

## Output Files

Local files are always written to:

- `deployments.json`
- `analytics/service_metrics.csv`
- `analytics/deployment_events.csv`
- `analytics/reverts.csv`
- `analytics/manifest.json`

If `PARTITION_BY_DATE=true` (default), CSV/manifest outputs are written under:

- `analytics/year=YYYY/month=MM/`

### CSV Columns

All CSV outputs include:

- `report_month`: reporting month label (`YYYY-MM`) when month-based runs are used.
- `snapshot_at`: timestamp when the run was executed.

### Manifest

`manifest.json` includes:

- `generated_at`
- `report_month`
- `window_start`
- `window_end`
- row counts per output file
- collection summary statistics

## SharePoint Upload

Set `UPLOAD=true` to enable upload. Uploaded target path is built from:

- `FOLDER_PATH`
- plus the partition suffix (`year=YYYY/month=MM`) when partitioning is enabled.

Upload failures are retried with backoff and included in the script result
summary.

## Exit Codes

- `0`: success.
- `1`: pipeline completed with failures (for example failed components or uploads).
- `2`: invalid CLI arguments.


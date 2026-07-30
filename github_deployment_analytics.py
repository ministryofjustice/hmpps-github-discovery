import argparse
import json
import os
import sys
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from processes.deployments import run_deployments_pipeline


def parse_bool_env(name: str, default: bool) -> bool:
  raw = os.getenv(name)
  if raw is None:
    return default
  return raw.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def parse_datetime(value: str) -> datetime:
  normalized = value.strip().replace('Z', '+00:00')
  parsed = datetime.fromisoformat(normalized)
  if parsed.tzinfo is None:
    return parsed.replace(tzinfo=timezone.utc)
  return parsed


def parse_month(value: str) -> datetime:
  try:
    parsed = datetime.strptime(value.strip(), '%Y-%m')
  except ValueError as error:
    raise argparse.ArgumentTypeError('Month must be in YYYY-MM format.') from error
  return parsed.replace(tzinfo=timezone.utc)


def previous_calendar_month_start(now: datetime) -> datetime:
  this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
  return this_month_start - relativedelta(months=1)


def build_runtime_config() -> dict:
  return {
    'upload': parse_bool_env('UPLOAD', False),
    'site_name': os.getenv('SITE_NAME', 'HMPPSSRE'),
    'drive_name': os.getenv('DRIVE_NAME', 'Documents'),
    'folder_path': os.getenv('FOLDER_PATH', 'analytics/deployments'),
    'partition_by_date': parse_bool_env('PARTITION_BY_DATE', True),
  }


def main() -> None:
  parser = argparse.ArgumentParser(description='Run the deployment pipeline.')
  parser.add_argument(
    '--month',
    type=parse_month,
    help='Reporting month in YYYY-MM format. Defaults to previous calendar month.',
  )
  parser.add_argument(
    '--since',
    type=parse_datetime,
    help='Optional custom window start in ISO 8601 format (must be used with --until).',
  )
  parser.add_argument(
    '--until',
    type=parse_datetime,
    help='Optional custom window end in ISO 8601 format (must be used with --since).',
  )
  args = parser.parse_args()

  if args.month and (args.since or args.until):
    parser.error('--month cannot be used with --since/--until')

  if (args.since and not args.until) or (args.until and not args.since):
    parser.error('--since and --until must be provided together')

  now = datetime.now(timezone.utc)
  if args.month:
    since_dt = args.month
    until_dt = args.month + relativedelta(months=1)
    report_month = args.month.strftime('%Y-%m')
  elif args.since and args.until:
    if args.until <= args.since:
      parser.error('--until must be later than --since')
    since_dt = args.since
    until_dt = args.until
    report_month = None
  else:
    since_dt = previous_calendar_month_start(now)
    until_dt = since_dt + relativedelta(months=1)
    report_month = since_dt.strftime('%Y-%m')

  result = run_deployments_pipeline(
    config=build_runtime_config(),
    since_dt=since_dt,
    until_dt=until_dt,
    report_month=report_month,
  )
  print(json.dumps(result, indent=2))
  if result.get('status') != 'success':
    sys.exit(1)


if __name__ == '__main__':
  main()

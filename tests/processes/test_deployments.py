from datetime import datetime, timezone

from processes.deployments import (
  build_month_partition,
  classify_github_error,
  flatten_deployments,
  format_duration,
  resolve_reporting_window,
  safe_ratio,
)


def test_classify_github_error_handles_temporary_and_permanent_cases():
  temporary_error = RuntimeError('timed out')
  assert classify_github_error(temporary_error) == ('temporary', None)

  permanent_error = RuntimeError('bad credentials')
  assert classify_github_error(permanent_error) == ('permanent', None)

  auth_error = RuntimeError('401 Unauthorized')
  # status is not available on this synthetic exception,
  # so it resolves to a generic permanent error.
  assert classify_github_error(auth_error)[0] == 'permanent'


def test_format_duration_returns_readable_hms_string():
  assert format_duration(3661) == '0d 01:01:01'
  assert format_duration(90061) == '1d 01:01:01'


def test_safe_ratio_handles_zero_denominator():
  assert safe_ratio(3, 0) is None
  assert safe_ratio(4, 8) == 0.5
  assert safe_ratio(1, 3) == 0.3333


def test_build_month_partition_uses_year_and_month():
  dt = datetime(2024, 6, 12, tzinfo=timezone.utc)
  assert build_month_partition(dt) == 'year=2024/month=06'


def test_resolve_reporting_window_defaults_to_previous_calendar_month():
  run_at = datetime(2024, 6, 15, 9, 30, tzinfo=timezone.utc)
  start, end = resolve_reporting_window(run_at, None, None)

  assert start == datetime(2024, 5, 1, 0, 0, tzinfo=timezone.utc)
  assert end == datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)


def test_resolve_reporting_window_with_custom_dates_is_preserved():
  since = datetime(2024, 4, 1, tzinfo=timezone.utc)
  until = datetime(2024, 5, 1, tzinfo=timezone.utc)
  start, end = resolve_reporting_window(
    datetime(2024, 6, 15, tzinfo=timezone.utc), since, until
  )

  assert start == since
  assert end == until


def test_flatten_deployments_builds_expected_csv_rows():
  snapshot_at = '2024-06-15T09:30:00+00:00'
  deployments = {
    'service-a': {
      'product': 'prod-123',
      'product_name': 'Example Product',
      'monorepo': False,
      'total_prs': 10,
      'prs_with_deployments': 5,
      'deployment_stats': {'success': 4, 'error': 1, 'other': 0},
      'reverts': [{'pr_number': 42, 'title': 'Revert release', 'referenced_pr': '41'}],
      'errors': ['something went wrong'],
      'metrics': {
        'successful_deployments': 4,
        'revert_count': 1,
        'time_to_deploy': {
          'average_minutes': 27.5,
          'median_minutes': 25.0,
        },
      },
      'merge_to_deploy_times': [
        {
          'pr_number': 99,
          'merged_at': '2024-06-01 12:00:00',
          'deployed_at': '2024-06-01 12:45:00',
          'duration_seconds': 2700,
          'status': 'success',
        }
      ],
    }
  }

  service_rows, deployment_rows, revert_rows = flatten_deployments(
    deployments, snapshot_at, report_month='2024-06'
  )

  assert len(service_rows) == 1
  assert service_rows[0]['service_key'] == 'service-a'
  assert service_rows[0]['total_prs'] == 10
  assert service_rows[0]['prs_with_deployments'] == 5
  assert service_rows[0]['successful_deployments'] == 4
  assert service_rows[0]['error_deployments'] == 1
  assert service_rows[0]['deployment_coverage_rate'] == 0.5
  assert service_rows[0]['deployment_success_rate'] == 0.8
  assert service_rows[0]['revert_rate'] == 0.1
  assert service_rows[0]['error_count'] == 1

  assert len(deployment_rows) == 1
  assert deployment_rows[0]['pr_number'] == 99
  assert deployment_rows[0]['duration_minutes'] == 45.0
  assert deployment_rows[0]['was_successful'] is True
  assert deployment_rows[0]['was_error'] is False

  assert len(revert_rows) == 1
  assert revert_rows[0]['revert_pr_number'] == 42
  assert revert_rows[0]['title'] == 'Revert release'
  assert revert_rows[0]['referenced_pr'] == '41'

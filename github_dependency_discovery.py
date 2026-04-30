#!/usr/bin/env python
"""Github dependency latest-version discovery.

This script gets the latest dependency versions from various sources 
such as GitHub repositories and
release notes and stores it in the Service Catalogue recommended-versions
table.

Required environment variables
------------------------------

Github (Credentials for Discovery app that has access to the repositories)
- GITHUB_APP_ID: Github App ID
- GITHUB_APP_INSTALLATION_ID: Github App Installation ID
- GITHUB_APP_PRIVATE_KEY: Github App Private Key

Service Catalogue
- SERVICE_CATALOGUE_API_ENDPOINT: Service Catalogue API endpoint
- SERVICE_CATALOGUE_API_KEY: Service

- SLACK_BOT_TOKEN: Slack Bot Token

Optional environment variables
- SLACK_NOTIFY_CHANNEL: Slack channel for notifications
- SLACK_ALERT_CHANNEL: Slack channel for alerts
- LOG_LEVEL: Log level (default: INFO)
"""

import re
from datetime import date, datetime

import requests
import yaml

from hmpps import ServiceCatalogue, GithubSession, Slack
from hmpps.services.job_log_handling import log_error, log_info, log_warning, job


class Services:
  def __init__(self):
    self.slack = Slack()
    self.sc = ServiceCatalogue()
    self.gh = GithubSession()


def _normalise_iso_datetime(value):
  if not value:
    return None
  if isinstance(value, datetime):
    return value.date().isoformat()
  if isinstance(value, date):
    return value.isoformat()
  if not isinstance(value, str):
    return str(value)
  try:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat()
  except ValueError:
    return value


def _record_matches_payload(record, payload):
  existing_name = (record.get('name') or '').lower()
  existing_type = (record.get('type') or '').lower() if record.get('type') else None
  target_name = (payload.get('name') or '').lower()
  target_type = (payload.get('type') or '').lower() if payload.get('type') else None

  existing_published_date = _normalise_iso_datetime(record.get('published_date'))
  target_published_date = _normalise_iso_datetime(payload.get('published_date'))

  return (
    existing_name == target_name
    and (record.get('version') or '') == (payload.get('version') or '')
    and existing_type == target_type
    and existing_published_date == target_published_date
    and (record.get('source') or '') == (payload.get('source') or '')
  )


def _get_latest_version_from_release_notes(gh, repo_name):
  repo = gh.get_org_repo(repo_name)
  published_at = None

  release_notes = repo.get_contents('release-notes', ref=repo.default_branch)
  candidate_files = []
  for item in release_notes:
    match = re.match(r'^(\d+)\.x\.md$', item.name)
    if match:
      candidate_files.append((int(match.group(1)), item.name))

  if not candidate_files:
    raise RuntimeError('No release notes matching <major>.x.md were found')

  _, latest_file = sorted(candidate_files, key=lambda x: x[0])[-1]
  release_notes_path = f'release-notes/{latest_file}'
  release_notes_content = gh.get_file_plain(repo, release_notes_path)
  if not release_notes_content:
    raise RuntimeError(f'Unable to read {release_notes_path}')

  first_heading = re.search(r'^#\s+([^\s]+)', release_notes_content, re.MULTILINE)
  if not first_heading:
    raise RuntimeError(f'Unable to parse latest version from {release_notes_path}')

  version = first_heading.group(1).strip()
  default_branch_sha = repo.get_branch(repo.default_branch).commit.sha

  # Best effort published date from latest commit touching this release-notes file.
  try:
    commits = repo.get_commits(path=release_notes_path)
    latest_commit = next(iter(commits), None)
    if latest_commit and latest_commit.commit and latest_commit.commit.committer:
      published_at = latest_commit.commit.committer.date.date().isoformat()
  except Exception as e:
    log_warning(
      f'Unable to determine published date for {repo_name}/{release_notes_path}: {e}'
    )

  source = (
    f'https://github.com/ministryofjustice/{repo_name}/blob/'
    f'{default_branch_sha}/{release_notes_path}?plain=1'
  )

  return {
    'version': version,
    'published_date': published_at,
    'source': source,
  }


def _get_latest_version_from_kotlin_build_file(gh, repo_name):
  repo = gh.get_org_repo(repo_name)
  build_file_path = 'build.gradle.kts'
  published_at = None

  build_file_content = gh.get_file_plain(repo, build_file_path)
  if not build_file_content:
    raise RuntimeError(f'Unable to read {build_file_path} from {repo_name}')

  allprojects_block = re.search(
    r'allprojects\s*\{.*?version\s*=\s*["\']([^"\']+)["\']',
    build_file_content,
    re.DOTALL,
  )
  if not allprojects_block:
    raise RuntimeError(
      f'Unable to parse allprojects version from {repo_name}/{build_file_path}'
    )

  version = allprojects_block.group(1).strip()
  default_branch_sha = repo.get_branch(repo.default_branch).commit.sha

  # Best effort published date from latest commit touching build.gradle.kts.
  try:
    commits = repo.get_commits(path=build_file_path)
    latest_commit = next(iter(commits), None)
    if latest_commit and latest_commit.commit and latest_commit.commit.committer:
      published_at = latest_commit.commit.committer.date.date().isoformat()
  except Exception as e:
    log_warning(
      f'Unable to determine published date for {repo_name}/{build_file_path}: {e}'
    )

  source = (
    f'https://github.com/ministryofjustice/{repo_name}/blob/'
    f'{default_branch_sha}/{build_file_path}?plain=1'
  )

  return {
    'version': version,
    'published_date': published_at,
    'source': source,
  }


def _get_latest_helm_chart_versions(chart_names):
  source = 'https://ministryofjustice.github.io/hmpps-helm-charts/index.yaml'
  try:
    response = requests.get(source, timeout=15)
    response.raise_for_status()
    index_data = yaml.safe_load(response.text) or {}
  except Exception as e:
    raise RuntimeError(f'Unable to read helm repository index: {e}')

  chart_entries = index_data.get('entries', {})
  results = {}

  for chart_name in chart_names:
    versions = chart_entries.get(chart_name, [])
    if not versions:
      raise RuntimeError(f'No helm chart versions found for {chart_name}')

    latest = versions[0] or {}
    version = latest.get('version')
    if not version:
      raise RuntimeError(f'No version field found for helm chart {chart_name}')

    published_date = None
    if latest.get('created'):
      published_date = _normalise_iso_datetime(latest.get('created'))

    results[chart_name] = {
      'version': version,
      'published_date': published_date,
      'source': source,
    }

  return results


def _get_latest_version_from_releases(gh, repo_name):
  repo = gh.get_org_repo(repo_name)
  published_at = None
  version = None

  def _resolve_tag_commit_sha(repo_obj, tag_name):
    try:
      ref = repo_obj.get_git_ref(f'tags/{tag_name}')
      sha = ref.object.sha
      # Annotated tags point to a tag object first; dereference to commit SHA.
      if ref.object.type == 'tag':
        tag_obj = repo_obj.get_git_tag(sha)
        return tag_obj.object.sha
      return sha
    except Exception as e:
      log_warning(f'Unable to resolve tag SHA for {repo_name}:{tag_name} - {e}')
      return None

  try:
    release = repo.get_latest_release()
    version = release.tag_name
    if release.published_at:
      published_at = release.published_at.date().isoformat()
  except Exception as e:
    log_warning(f'Unable to get latest release for {repo_name}: {e}')

  if not version:
    tags = repo.get_tags()
    first_tag = next(iter(tags), None)
    if not first_tag:
      raise RuntimeError(f'No release or tag found for {repo_name}')
    version = first_tag.name

  tag_sha = _resolve_tag_commit_sha(repo, version)
  if tag_sha:
    source = f'https://github.com/ministryofjustice/{repo_name}/tree/{tag_sha}'
  else:
    source = f'https://github.com/ministryofjustice/{repo_name}/releases/tag/{version}'

  return {
    'version': version,
    'published_date': published_at,
    'source': source,
  }


def _get_latest_version_for_action(gh, action_name):
  published_at = None
  version = None

  if '/' not in action_name or action_name.startswith('./'):
    raise RuntimeError(f'Invalid GitHub Action name: {action_name}')

  action_parts = action_name.split('/')
  if len(action_parts) < 2:
    raise RuntimeError(f'Invalid GitHub Action name: {action_name}')
  repo_name = f'{action_parts[0]}/{action_parts[1]}'
  repo = gh.session.get_repo(repo_name)

  def _resolve_tag_commit_sha(repo_obj, tag_name):
    try:
      ref = repo_obj.get_git_ref(f'tags/{tag_name}')
      sha = ref.object.sha
      if ref.object.type == 'tag':
        tag_obj = repo_obj.get_git_tag(sha)
        return tag_obj.object.sha
      return sha
    except Exception as e:
      log_warning(f'Unable to resolve tag SHA for {repo_name}:{tag_name} - {e}')
      return None

  try:
    release = repo.get_latest_release()
    version = release.tag_name
    if release.published_at:
      published_at = release.published_at.date().isoformat()
  except Exception as e:
    log_warning(f'Unable to get latest release for {repo_name}: {e}')

  if not version:
    tags = repo.get_tags()
    first_tag = next(iter(tags), None)
    if not first_tag:
      raise RuntimeError(f'No release or tag found for {repo_name}')
    version = first_tag.name

  tag_sha = _resolve_tag_commit_sha(repo, version)
  if tag_sha:
    source = f'https://github.com/{repo_name}/tree/{tag_sha}'
  else:
    source = f'https://github.com/{repo_name}/releases/tag/{version}'

  return {
    'version': version,
    'published_date': published_at,
    'source': source,
  }


def _get_unique_github_actions_from_components(sc):
  action_names = set()
  components = sc.get_all_records(sc.components_get)

  for component in components:
    versions = component.get('versions') or {}
    github_actions = versions.get('Github Actions') or {}
    if isinstance(github_actions, dict):
      for action_name in github_actions.keys():
        if 'ministryofjustice' in action_name.lower():
          continue
        action_names.add(action_name)
  return sorted(action_names)


def _build_recommended_versions_index(records):
  index = {}
  for record in records:
    name = (record.get('name') or '').lower()
    if not name:
      continue
    index.setdefault(name, []).append(record)
  return index


def _update_recommended_version(
  sc,
  recommended_versions_index,
  dependency_name,
  dependency_type,
  latest_version,
):
  dependency_key = dependency_name.lower()
  target_records = recommended_versions_index.get(dependency_key, [])

  payload = {
    'name': dependency_name,
    'version': latest_version['version'],
    'type': dependency_type,
    'published_date': latest_version['published_date'],
    'source': latest_version['source'],
  }

  updates = 0
  creates = 0

  if not target_records:
    created = sc.add('recommended-versions', payload)
    if not created:
      raise RuntimeError(
        f'Failed to create recommended-versions record for {dependency_name}'
      )

    created_record = {
      'name': payload['name'],
      'type': payload['type'],
      'version': payload['version'],
      'published_date': payload['published_date'],
      'source': payload['source'],
      'documentId': (created.get('data') or {}).get('documentId')
      if isinstance(created, dict)
      else None,
    }
    recommended_versions_index.setdefault(dependency_key, []).append(created_record)
    creates = 1
    return {'updates': updates, 'creates': creates}

  for record in target_records:
    document_id = record.get('documentId')
    if not document_id:
      log_warning('Skipping recommended-versions record without documentId')
      continue

    if _record_matches_payload(record, payload):
      log_info(
        f'recommended-versions record already matches payload; skipping update'
      )
      continue

    if sc.update('recommended-versions', document_id, payload):
      record['name'] = payload['name']
      record['type'] = payload['type']
      record['version'] = payload['version']
      record['published_date'] = payload['published_date']
      record['source'] = payload['source']
      updates += 1
    else:
      log_error(f'Failed to update recommended-versions record {document_id}')

  return {'updates': updates, 'creates': creates}


def create_summary(services, changed_dependency_results, counts):
  summary = 'Github Dependency Latest-Version Discovery completed OK\n'
  summary += '\n\nRECOMMENDED-VERSIONS SUMMARY\n============================\n'
  summary += f'- records_updated: {counts["updates"]}\n'
  summary += f'- records_created: {counts["creates"]}\n'
  for result in changed_dependency_results:
    summary += f'- dependency: {result["type"]} : {result["name"]}\n'
    summary += f'\tlatest_version: {result["latest"]["version"]}\n'
    summary += f'\tpublished_date: {result["latest"]["published_date"]}\n'
    summary += f'\tsource: {result["latest"]["source"]}\n'
  summary += (
    '\n_(generated by <https://github.com/ministryofjustice/hmpps-github-discovery|'
    'hmpps-github-discovery>)_'
  )

  services.slack.notify(summary)
  log_info(summary)


def main():
  job.name = 'hmpps-github-discovery-dependencies-latest'

  services = Services()
  slack = services.slack
  sc = services.sc
  gh = services.gh

  if not sc.connection_ok:
    slack.alert('*Github Dependency Discovery failed*: Unable to connect to the SC')
    raise SystemExit()

  if not gh.org:
    slack.alert('*Github Dependency Discovery failed*: Unable to connect to Github')
    log_error('*Github Dependency Discovery failed*: Unable to connect to Github')
    sc.update_scheduled_job('Failed')
    raise SystemExit()

  try:
    changed_dependency_results = []
    total_updates = 0
    total_creates = 0
    recommended_versions_records = sc.get_all_records('recommended-versions')
    recommended_versions_index = _build_recommended_versions_index(
      recommended_versions_records
    )

    latest_circleci = _get_latest_version_from_release_notes(gh, 'hmpps-circleci-orb')
    circleci_counts = _update_recommended_version(
      sc,
      recommended_versions_index,
      dependency_name='hmpps_orb',
      dependency_type='CircleCi',
      latest_version=latest_circleci,
    )
    total_updates += circleci_counts['updates']
    total_creates += circleci_counts['creates']
    if circleci_counts['updates'] > 0 or circleci_counts['creates'] > 0:
      changed_dependency_results.append(
        {
          'name': 'hmpps_orb',
          'type': 'CircleCi',
          'latest': latest_circleci,
        }
      )

    latest_gradle = _get_latest_version_from_release_notes(
      gh, 'hmpps-gradle-spring-boot'
    )
    gradle_counts = _update_recommended_version(
      sc,
      recommended_versions_index,
      dependency_name='hmpps_gradle_spring_boot',
      dependency_type='Gradle',
      latest_version=latest_gradle,
    )
    total_updates += gradle_counts['updates']
    total_creates += gradle_counts['creates']
    if gradle_counts['updates'] > 0 or gradle_counts['creates'] > 0:
      changed_dependency_results.append(
        {
          'name': 'hmpps_gradle_spring_boot',
          'type': 'Gradle',
          'latest': latest_gradle,
        }
      )

    latest_sqs_gradle = _get_latest_version_from_release_notes(
      gh, 'hmpps-spring-boot-sqs'
    )
    sqs_gradle_counts = _update_recommended_version(
      sc,
      recommended_versions_index,
      dependency_name='hmpps_sqs_spring_boot_starter',
      dependency_type='gradle',
      latest_version=latest_sqs_gradle,
    )
    total_updates += sqs_gradle_counts['updates']
    total_creates += sqs_gradle_counts['creates']
    if sqs_gradle_counts['updates'] > 0 or sqs_gradle_counts['creates'] > 0:
      changed_dependency_results.append(
        {
          'name': 'hmpps_sqs_spring_boot_starter',
          'type': 'gradle',
          'latest': latest_sqs_gradle,
        }
      )

    latest_kotlin_gradle = _get_latest_version_from_kotlin_build_file(
      gh, 'hmpps-kotlin-lib'
    )
    kotlin_gradle_counts = _update_recommended_version(
      sc,
      recommended_versions_index,
      dependency_name='hmpps_kotln_spring_boot_starter',
      dependency_type='gradle',
      latest_version=latest_kotlin_gradle,
    )
    total_updates += kotlin_gradle_counts['updates']
    total_creates += kotlin_gradle_counts['creates']
    if kotlin_gradle_counts['updates'] > 0 or kotlin_gradle_counts['creates'] > 0:
      changed_dependency_results.append(
        {
          'name': 'hmpps_kotln_spring_boot_starter',
          'type': 'gradle',
          'latest': latest_kotlin_gradle,
        }
      )

    latest_github_actions = _get_latest_version_from_releases(
      gh, 'hmpps-github-actions'
    )
    github_actions_counts = _update_recommended_version(
      sc,
      recommended_versions_index,
      dependency_name='hmpps-github-actions',
      dependency_type='Github Workflows',
      latest_version=latest_github_actions,
    )
    total_updates += github_actions_counts['updates']
    total_creates += github_actions_counts['creates']
    if github_actions_counts['updates'] > 0 or github_actions_counts['creates'] > 0:
      changed_dependency_results.append(
        {
          'name': 'hmpps-github-actions',
          'type': 'Github Workflows',
          'latest': latest_github_actions,
        }
      )

    latest_shared_actions = _get_latest_version_from_releases(
      gh, 'hmpps-github-shared-actions'
    )
    shared_actions_counts = _update_recommended_version(
      sc,
      recommended_versions_index,
      dependency_name='hmpps-github-shared-actions',
      dependency_type='Github Workflows',
      latest_version=latest_shared_actions,
    )
    total_updates += shared_actions_counts['updates']
    total_creates += shared_actions_counts['creates']
    if shared_actions_counts['updates'] > 0 or shared_actions_counts['creates'] > 0:
      changed_dependency_results.append(
        {
          'name': 'hmpps-github-shared-actions',
          'type': 'Github Workflows',
          'latest': latest_shared_actions,
        }
      )

    github_action_names = _get_unique_github_actions_from_components(sc)
    log_info(f'Found {len(github_action_names)} unique GitHub Actions across components')
    log_info(f'GitHub Actions: {github_action_names}')
    for action_name in github_action_names:
      latest_action = _get_latest_version_for_action(gh, action_name)
      action_counts = _update_recommended_version(
        sc,
        recommended_versions_index,
        dependency_name=action_name,
        dependency_type='Github Actions',
        latest_version=latest_action,
      )
      total_updates += action_counts['updates']
      total_creates += action_counts['creates']
      if action_counts['updates'] > 0 or action_counts['creates'] > 0:
        changed_dependency_results.append(
          {
            'name': action_name,
            'type': 'Github Actions',
            'latest': latest_action,
          }
        )

    helm_chart_names = [
      'clamav',
      'generic-service',
      'generic-prometheus-alerts',
      'generic-data-analytics-extractor',
      'generic-aws-prometheus-alerts',
    ]
    latest_helm_versions = _get_latest_helm_chart_versions(helm_chart_names)
    for chart_name in helm_chart_names:
      helm_counts = _update_recommended_version(
        sc,
        recommended_versions_index,
        dependency_name=chart_name,
        dependency_type='Helm Dependencies',
        latest_version=latest_helm_versions[chart_name],
      )
      total_updates += helm_counts['updates']
      total_creates += helm_counts['creates']
      if helm_counts['updates'] > 0 or helm_counts['creates'] > 0:
        changed_dependency_results.append(
          {
            'name': chart_name,
            'type': 'Helm Dependencies',
            'latest': latest_helm_versions[chart_name],
          }
        )

    counts = {'updates': total_updates, 'creates': total_creates}
  except Exception as e:
    log_error(f'Github dependency discovery failed: {e}')
    slack.alert(f'*Github Dependency Discovery failed*: {e}')
    sc.update_scheduled_job('Failed')
    raise SystemExit()

  create_summary(services, changed_dependency_results, counts)

  if job.error_messages:
    sc.update_scheduled_job('Errors')
    log_info('Github dependency latest-version discovery job completed with errors.')
  else:
    sc.update_scheduled_job('Succeeded')
    log_info('Github dependency latest-version discovery job completed successfully.')


if __name__ == '__main__':
  main()

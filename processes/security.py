import re

# hmpps
from hmpps import update_dict
from hmpps.services.job_log_handling import log_debug, log_info, log_warning, log_error

# local
from includes import standards
from datetime import datetime, timezone
import requests


# Repository variables - processed daily to ensure that the Service Catalogue
# is up-to-date
def get_repo_variables(services, repo, component_name):
  repo_vars = {}
  repo_var_list = [
    ('product', 'HMPPS_PRODUCT_ID'),
    ('slack_channel_security_scans_notify', 'SECURITY_ALERTS_SLACK_CHANNEL_ID'),
    ('slack_channel_prod_release_notify', 'PROD_RELEASES_SLACK_CHANNEL'),
    ('slack_channel_nonprod_release_notify', 'NONPROD_RELEASES_SLACK_CHANNEL'),
  ]
  for var in repo_var_list:
    try:
      repo_var = repo.get_variable(var[1])
      repo_var_value = repo_var.value
      if var[1] == 'HMPPS_PRODUCT_ID':
        if sc_product_id := services.sc.get_id('products', 'p_id', repo_var_value):
          repo_vars[var[0]] = sc_product_id
        else:
          log_debug(f'Unable to find product entry for {repo_var_value}')
      else:
        repo_vars[var[0]] = repo_var.value
    except Exception as e:
      if '404' in str(e):
        log_debug(f'No {var[1]} repo variable found for {component_name}')
      else:
        log_debug(f'Could not get {var[1]} repo variable for {component_name} - {e}')
      pass
  log_debug(f'Repository variables: {repo_vars}')
  return repo_vars


class WaitingRunsDetector:
  def __init__(self, services, repo):
    self.owner = services.gh.org.login
    self.api = 'https://api.github.com'
    self.headers = {
      'Authorization': f'Bearer {services.gh.rest_token}',
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    }
    self.repo_name = repo.name
    self.default_branch = repo.default_branch

  def list_waiting_runs(self):
    runs = []
    page = 1
    while True:
      url = f'{self.api}/repos/{self.owner}/{self.repo_name}/actions/runs'
      params = {'status': 'waiting', 'per_page': 100, 'page': page}
      r = requests.get(url, headers=self.headers, params=params, timeout=20)
      r.raise_for_status()
      data = r.json()
      batch = data.get('workflow_runs', [])
      runs.extend(batch)
      if len(batch) < 100:
        break
      page += 1
    return runs

  def latest_success_for(self, workflow_id, branch):
    # Try to fetch a single latest success; fallback to completed if needed
    url = f'{self.api}/repos/{self.owner}/{self.repo_name}/actions/workflows/{workflow_id}/runs'
    for params in (
      {'branch': branch, 'status': 'success', 'per_page': 1},
      {'branch': branch, 'status': 'completed', 'per_page': 3},
    ):
      r = requests.get(url, headers=self.headers, params=params, timeout=20)
      if r.status_code == 200:
        runs = r.json().get('workflow_runs', [])
        # prefer success if we got it; else pick first with conclusion==success
        if params['status'] == 'success' and runs:
          return runs[0]['created_at']
        for rr in runs:
          if rr.get('conclusion') == 'success':
            return rr['created_at']
    return None

  def get_pending_deployments(self, run_id):
    url = f'{self.api}/repos/{self.owner}/{self.repo_name}/actions/runs/{run_id}/pending_deployments'
    r = requests.get(url, headers=self.headers, timeout=20)
    log_debug(
      f'Status code for pending deployments for run_id {run_id}: {r.status_code}'
    )
    if r.status_code == 200:
      return r.json(), None
    if 500 <= r.status_code < 600:
      return None, {
        'status': r.status_code,
        'request_id': r.headers.get('x-github-request-id'),
      }
    r.raise_for_status()
    return None, None

  def find(self):
    waiters = self.list_waiting_runs()
    # Sort oldest first
    waiters.sort(key=lambda w: w['created_at'])
    # Build one-liner cache for latest success per (workflow_id, branch)
    cache = {}
    now = datetime.now(timezone.utc)

    for w in waiters:
      created = datetime.fromisoformat(w['created_at'].replace('Z', '+00:00'))

      # Check if superseded by same branch OR default branch (e.g. main)
      is_superseded = False
      for branch_to_check in {w['head_branch'], self.default_branch}:
        key = (w['workflow_id'], branch_to_check)
        if key not in cache:
          cache[key] = self.latest_success_for(*key)

        latest_ok = cache[key]
        if latest_ok:
          latest_ok_dt = datetime.fromisoformat(latest_ok.replace('Z', '+00:00'))
          if latest_ok_dt > created:
            is_superseded = True
            break

      if is_superseded:
        continue

      # Only now ask pending_deployments
      log_debug(f'getting pending deployments for {w["id"]}')
      pd, err = self.get_pending_deployments(w['id'])
      if err:  # 5xx -> log and keep going
        log_info(
          f'Encountered issues getting pending deployments: {err}'
        )  # log err["request_id"]
        continue
      if pd:  # non-empty means environment gate; actionable
        age_days = (now - created).days
        return {
          'run_id': w['id'],
          'url': w['html_url'],
          'branch': w['head_branch'],
          'workflow_id': w['workflow_id'],
          'age_days': age_days,
          'environments': [p['environment']['name'] for p in pd],
        }
      # else: waiting for other reasons (e.g., concurrency) -> try next

    return None  # no actionable waiting runs


def get_waiting_runs(services, repo):
  return WaitingRunsDetector(services, repo).find()


# Read the npmrc configuration from the root of the project
def get_npmrc_config(gh, repo):
  """Parse .npmrc file and extract configuration settings."""
  npmrc_config = {}
  if npmrc_content := gh.get_file_plain(repo, '.npmrc'):
    try:
      # Parse each line looking for key = value pairs
      for line in npmrc_content.splitlines():
        # Skip comments and empty lines
        line = line.strip()
        if not line or line.startswith('#'):
          continue

        # Match "key = value" pattern
        if match := re.match(r'^\s*([a-zA-Z0-9_-]+)\s*=\s*(.+)\s*$', line):
          key, value = match.groups()
          npmrc_config[key] = value.strip()

      log_debug(f'Found npmrc_config: {npmrc_config}')
    except Exception as e:
      log_warning(f'Unable to parse .npmrc file - {e}')
      pass

  if npmrc_config:
    return npmrc_config
  else:
    log_debug('No .npmrc file found or no valid configuration')
  return None


def get_npmrc_ignore_scripts(services, repo):
  """Get the ignore-scripts setting from .npmrc."""
  if repo.language == 'JavaScript' or repo.language == 'TypeScript':
    if npmrc_config := get_npmrc_config(services.gh, repo):
      ignore_scripts_value = npmrc_config.get('ignore-scripts', '')
      # Convert to boolean if it's 'true' or 'false'
      if ignore_scripts_value.lower() == 'true':
        return True
      elif ignore_scripts_value.lower() == 'false':
        return False


######################################################
# Component Security Scanning - only runs once per day
######################################################


def process_sc_component_security(services, component, **kwargs):
  # Set some convenient defaults
  sc = services.sc
  gh = services.gh
  component_name = component.get('name')
  github_repo = component.get('github_repo')

  # Reset the data ready for updating
  data = {}  # dictionary to hold all the updated data for the component
  component_flags = {}

  try:
    repo = gh.get_org_repo(f'{github_repo}')
  except Exception as e:
    log_error(
      f'ERROR accessing ministryofjustice/{github_repo}, '
      f'check github app has permissions to see it. {e}'
    )
    return component_flags

  # Codescanning Alerts
  #####################

  if codescanning_summary := gh.get_codescanning_summary(repo):
    update_dict(data, 'codescanning_summary', codescanning_summary)
    component_flags['repos_with_vulnerabilities'] = 1

  # Repository Standards
  ######################

  if repo_standards := standards.get_standards_compliance(repo):
    update_dict(data, 'standards_compliance', repo_standards)

  # Repository variables
  ######################
  if repo_variables := get_repo_variables(services, repo, component_name):
    data.update(repo_variables)

  # npmrc ignore scripts settings
  ###############################
  ignore_scripts = get_npmrc_ignore_scripts(services, repo)
  if isinstance(ignore_scripts, bool):
    log_info(f'Updating npm ignore-scripts setting: {ignore_scripts}')
    update_dict(
      data,
      'security_settings',
      {'npm': {'ignore_scripts': ignore_scripts}},
    )
  else:
    log_debug(f'npm ignore-scripts setting not found for {repo.name}')

  # Open dependabot/snyk/renovate PRs
  ####################################
  # if open_prs := get_open_prs(repo):
  #   update_dict(data, 'security_settings', {'open_dependency_prs': open_prs})

  # Open runs waiting for manual intervention
  ####################################
  runs_list = get_waiting_runs(services, repo)
  data.update({'workflow_runs_waiting': runs_list})

  # This will ensure the service catalogue has the latest collection of repository
  # variables. Update component with all results in data dictionary
  # if there's data to do so
  if data:
    if not sc.update(sc.components, component['documentId'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags

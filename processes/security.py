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


def get_legit_waiting_runs(repo, rest_token, max_runs=200):
  """
  Return waiting runs that (a) are actually blocked by environment protection and
  (b) are NOT superseded by a newer success on the same workflow+branch.
  """
  headers = {
    'Accept': 'application/vnd.github+json',
    'Authorization': f'Bearer {rest_token}',
    'X-GitHub-Api-Version': '2022-11-28',
  }

  def _pending_deployments(run_id):
    # GET /repos/{owner}/{repo}/actions/runs/{run_id}/pending_deployments
    url = f'{repo._requester.base_url}/repos/{repo.owner.login}/{repo.name}/actions/runs/{run_id}/pending_deployments'
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()  # list (possibly empty): each item contains environment, reviewers, wait_timer, etc.

  now = datetime.now(timezone.utc)
  legit = []
  all_waiters = []

  # 1) All 'waiting' runs (GitHub reserves this status; surfaced via the REST filter).
  waiting = repo.get_workflow_runs(status='waiting')

  for i, run in enumerate(waiting):
    if i >= max_runs:
      break

    created = (
      run.created_at
      if run.created_at.tzinfo
      else run.created_at.replace(tzinfo=timezone.utc)
    )
    pd = _pending_deployments(
      run.id
    )  # empty => not an env gate (likely concurrency, runners, etc.)

    # 2) Find newer success on same workflow+branch to mark as superseded
    try:
      wf = repo.get_workflow(run.workflow_id)
      completed = wf.get_runs(branch=run.head_branch, status='completed')
    except Exception:
      completed = repo.get_workflow_runs(branch=run.head_branch, status='completed')

    superseder = None
    for r2 in completed:
      if getattr(r2, 'workflow_id', None) != run.workflow_id:
        continue
      if r2.conclusion == 'success':
        r2_created = (
          r2.created_at
          if r2.created_at.tzinfo
          else r2.created_at.replace(tzinfo=timezone.utc)
        )
        if r2_created > created:
          superseder = {
            'id': r2.id,
            'url': r2.html_url,
            'created_at': r2_created.isoformat(),
          }
          break

    row = {
      'id': run.id,
      'name': run.name,
      'url': run.html_url,
      'branch': run.head_branch,
      'raiser': run.actor.login if run.actor else None,
      'age_days': (now - created).days,
      'environments': [item['environment']['name'] for item in pd] if pd else [],
      'pending_deployments': pd,  # contains reviewers / wait_timer
      'superseded_by_newer_success': superseder,
    }
    all_waiters.append(row)

    log_debug(f'{all_waiters}')
    # Keep only legitimate, actionable waiters:
    if pd and superseder is None:
      legit.append(row)

  return legit, all_waiters


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
  runs_list, all_waiters = get_legit_waiting_runs(repo, gh.rest_token)
  if runs_list:
    data.update({'workflow_runs_waiting': runs_list})

  # This will ensure the service catalogue has the latest collection of repository
  # variables. Update component with all results in data dictionary
  # if there's data to do so
  if data:
    if not sc.update(sc.components, component['documentId'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags

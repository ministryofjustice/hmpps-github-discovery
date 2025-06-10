import requests
from base64 import b64decode
import json
import yaml
import jwt
import re
from github import Auth, Github
from github.GithubException import UnknownObjectException
from datetime import datetime, timedelta, timezone
import processes.scheduled_jobs as sc_scheduled_job
from utilities.job_log_handling import (
  log_debug,
  log_error,
  log_warning,
  log_info,
  log_critical,
)
from includes.values import actions_whitelist


class GithubSession:
  def __init__(self, params):
    self.private_key = b64decode(params['app_private_key']).decode('ascii')
    self.app_id = params['app_id']
    self.app_installation_id = params['app_installation_id']

    self.auth()
    if self.session:
      try:
        rate_limit = self.session.get_rate_limit()
        self.core_rate_limit = rate_limit.core
        log_info(f'Github API: {rate_limit}')
        # test fetching organisation name
        self.org = self.session.get_organization('ministryofjustice')
      except Exception as e:
        log_critical('Unable to get Github Organisation.')

  def auth(self):
    try:
      auth = Auth.Token(self.get_access_token())
      self.session = Github(auth=auth, pool_size=50)
    except Exception as e:
      log_critical('Unable to connect to the github API.')

  def get_access_token(self):
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    payload = {'iat': now, 'exp': now + timedelta(minutes=10), 'iss': self.app_id}
    jwt_token = jwt.encode(payload, self.private_key, algorithm='RS256')
    headers = {
      'Authorization': f'Bearer {jwt_token}',
      'Accept': 'application/vnd.github.v3+json',
    }
    response = requests.post(
      f'https://api.github.com/app/installations/{self.app_installation_id}/access_tokens',
      headers=headers,
    )
    response.raise_for_status()
    return response.json()['token']

  def test_connection(self):
    # Test auth and connection to github
    try:
      rate_limit = self.session.get_rate_limit()
      self.core_rate_limit = rate_limit.core
      log_info(f'Github API: {rate_limit}')
      # test fetching organisation name
      self.org = self.session.get_organization('ministryofjustice')
      return True
    except Exception as e:
      log_critical('Unable to connect to the github API.')
      raise SystemExit(e) from e
      return None

  def get_rate_limit(self):
    try:
      if self.session:
        return self.session.get_rate_limit().core
    except Exception as e:
      log_error(f'Error getting rate limit: {e}')
      return None

  def get_org_repo(self, repo_name):
    repo = None
    try:
      repo = self.org.get_repo(repo_name)
    except Exception as e:
      log_error(f'Error trying to get the repo {repo_name} from Github: {e}')
      return None
    return repo

  def get_file_yaml(self, repo, path):
    try:
      file_contents = repo.get_contents(path)
      contents = b64decode(file_contents.content).decode().replace('\t', '  ')
      yaml_contents = yaml.safe_load(contents)
      return yaml_contents
    except UnknownObjectException:
      log_debug(f'404 File not found {repo.name}:{path}')
    except Exception as e:
      log_error(f'Error getting yaml file ({path}): {e}')

  def get_file_json(self, repo, path):
    try:
      file_contents = repo.get_contents(path)
      json_contents = json.loads(b64decode(file_contents.content))
      return json_contents
    except UnknownObjectException:
      log_debug(f'404 File not found {repo.name}:{path}')
      return None
    except Exception as e:
      log_error(f'Error getting json file ({path}): {e}')
      return None

  def get_file_plain(self, repo, path):
    try:
      file_contents = repo.get_contents(path)
      plain_contents = b64decode(file_contents.content).decode()
      return plain_contents
    except UnknownObjectException:
      log_debug(f'404 File not found {repo.name}:{path}')
      return None
    except Exception as e:
      log_error(f'Error getting contents from file ({path}): {e}')
      return None

  def find_uses(self, data, key='uses', result=None):
    if result is None:
      result = []

    def is_whitelisted(action):
      return any(re.match(pattern, action) for pattern in actions_whitelist)

    if isinstance(data, dict):
      for k, v in data.items():
        if k == key:
          log_debug(f'found key {k} | value:{v}')
          if not is_whitelisted(v):
            log_debug(f'action {v} is not whitelisted - adding to the list')
            result.append(v)
        else:
          self.find_uses(v, key, result)
    elif isinstance(data, list):
      for item in data:
        self.find_uses(item, key, result)

    return result

  def get_actions(self, repo):
    github_actions = []
    try:
      github_dir = repo.get_contents(
        '.github', ref=repo.get_branch(repo.default_branch).commit.sha
      )
      while github_dir:
        actions = {}
        file = github_dir.pop(0)
        if file.type == 'dir':
          github_dir.extend(repo.get_contents(file.path))
        else:
          if file.name.endswith('.yml'):
            log_debug(f'File found: {file.path}')
            action_filename = file.path
            actions = self.get_file_yaml(repo, action_filename)
            if uses := self.find_uses(actions):
              action_refs = {'filename': action_filename, 'actions': uses}
              github_actions.append(action_refs)
              log_debug(f'Actions: {action_refs}')
    except Exception as e:
      log_warning(f'Unable to load the .github folder for {repo.name}: {e}')
    return github_actions

  def api_get(self, api):
    response_json = {}
    log_debug(f'making API call: {api}')
    # GitHub API URL to check security and analysis settings
    url = f'https://api.github.com/{api}'
    token = self.get_access_token()
    log_debug(f'token is: {token}')
    # Headers for the request
    headers = {
      'Authorization': f'token {token}',
      'Accept': 'application/vnd.github.v3+json',
    }
    try:
      # Make the request to check security and analysis settings

      # Check the response status
      response = requests.get(url, headers=headers)
      if response.status_code == 200:
        response_json = response.json()
      else:
        log_error(
          f'Github API GET call failed with response code {response.status_code}'
        )

    except Exception as e:
      log_error(f'Error when making Github API: {e}')
    return response_json

  def get_codescanning_summary(self, repo):
    summary = {}
    alerts = []
    try:
      data = repo.get_codescan_alerts()
      if data:
        for alert in (a for a in data if a.state != 'fixed'):
          # log_debug(
          #   f'\n\nalert is: {json.dumps(alert.raw_data, indent=2)}\n============================'
          # )
          # some alerts don't have severity levels
          if alert.rule.security_severity_level:
            severity = alert.rule.security_severity_level.upper()
          else:
            severity = ''
          alert_data = {
            'tool': alert.tool.name,
            'cve': alert.rule.id,
            'severity': severity,
            'url': alert.html_url,
          }
          alerts.append(alert_data)

          log_debug(f'Alert data is:\n{json.dumps(alert_data, indent=2)}')
    except Exception as e:
      log_warning(f'Unable to retrieve codescanning data: {e}')
      # Dictionary to store the best severity per CVE
    vulnerabilities = {}

    log_debug(f'Full alert list:\n{json.dumps(alerts, indent=2)}')
    if alerts:
      # Loop through the alerts
      for alert in alerts:
        cve = alert['cve']
        severity = alert['severity']
        url = alert['url']

        if cve not in vulnerabilities:
          vulnerabilities[cve] = {
            'severity': severity if severity else 'UNKNOWN',
            'url': url,
          }
        else:
          if severity and (
            vulnerabilities[cve]['severity'] == 'UNKNOWN'
            or severity > vulnerabilities[cve]['severity']
          ):
            vulnerabilities[cve] = {'severity': severity, 'url': url}

      log_info(f'vulnerabilities: {json.dumps(vulnerabilities, indent=2)}')

      # Define severity ranking
      severity_order = {'UNKNOWN': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4}

      # Function to get severity rank
      def get_severity_order(severity):
        return severity_order.get(severity, 0)

      # Sort the CVEs by severity
      sorted_vulnerabilities = {}
      for vulnerability in sorted(
        vulnerabilities.items(),
        key=lambda item: get_severity_order(item[1]['severity']),
        reverse=True,
      ):
        sorted_vulnerabilities[vulnerability[0]] = vulnerability[1]

      # Count severities (adding empty ones to 'UNKNOWN')
      counts = {}
      for vulnerability in vulnerabilities.values():
        if severity := vulnerability.get('severity'):  # Skip empty severities
          counts[severity] = counts.get(severity, 0) + 1
        else:
          counts['UNKNOWN'] = counts.get('UNKNOWN', 0) + 1

      log_info(f'counts: {json.dumps(counts, indent=2)}')

      summary = {
        'counts': counts,
        'vulnerabilities': sorted_vulnerabilities,
      }
    return summary

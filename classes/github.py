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

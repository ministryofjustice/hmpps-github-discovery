#!/usr/bin/env python
'''Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue'''
import os
import http.server
import socketserver
import threading
import logging
import tempfile
from time import sleep
from datetime import datetime, timedelta, timezone
from base64 import b64decode
import re
import json
import yaml
import github
import requests
from dockerfile_parse import DockerfileParser
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import base64
import jwt
from github import Github, Auth
from github.GithubException import UnknownObjectException

SC_API_ENDPOINT = os.getenv('SERVICE_CATALOGUE_API_ENDPOINT')
SC_API_TOKEN = os.getenv('SERVICE_CATALOGUE_API_KEY')
GITHUB_APP_ID = int(os.getenv('GITHUB_APP_ID'))
GITHUB_APP_INSTALLATION_ID = int(os.getenv('GITHUB_APP_INSTALLATION_ID'))
GITHUB_APP_PRIVATE_KEY = os.getenv('GITHUB_APP_PRIVATE_KEY')
REFRESH_INTERVAL_HOURS = int(os.getenv('REFRESH_INTERVAL_HOURS', '6'))
CIRCLECI_TOKEN = os.getenv('CIRCLECI_TOKEN')
CIRCLECI_API_ENDPOINT = os.getenv(
  'CIRCLECI_API_ENDPOINT',
  'https://circleci.com/api/v1.1/project/gh/ministryofjustice/',
)
SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')

# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
MAX_THREADS = 10
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# limit results for testing/dev
# See strapi filter syntax https://docs.strapi.io/dev-docs/api/rest/filters-locale-publication
# Example filter string = '&filters[name][$contains]=example'
SC_FILTER = os.getenv('SC_FILTER', '')
SC_PAGE_SIZE = 10
SC_PAGINATION_PAGE_SIZE = f'&pagination[pageSize]={SC_PAGE_SIZE}'
# Example Sort filter
# SC_SORT='&sort=updatedAt:asc'
SC_SORT = ''
SC_ENDPOINT = f'{SC_API_ENDPOINT}/v1/components?populate=environments,latest_commit{SC_FILTER}{SC_PAGINATION_PAGE_SIZE}{SC_SORT}'
SC_ENDPOINT_TEAMS = f'{SC_API_ENDPOINT}/v1/github-teams'
SC_ENDPOINT_COMPONENTS = f'{SC_API_ENDPOINT}/v1/components'
SC_PRODUCT_FILTER = os.getenv(
  'SC_PRODUCT_FILTER',
  '&fields[0]=slack_channel_id&fields[1]=slack_channel_name&fields[2]=p_id&fields[3]=name',
)
SC_PRODUCT_ENDPOINT = f'{SC_API_ENDPOINT}/v1/products?populate=environments{SC_PRODUCT_FILTER}{SC_PAGINATION_PAGE_SIZE}{SC_SORT}'
SC_PRODUCT_UPDATE_ENDPOINT = f'{SC_API_ENDPOINT}/v1/products'
ALERTMANAGER_ENDPOINT = os.getenv('ALERTMANAGER_ENDPOINT','http://monitoring-alerts-service.cloud-platform-monitoring-alerts:8080/alertmanager/status')
alertmanager_json_data = ''

class HealthHttpRequestHandler(http.server.SimpleHTTPRequestHandler):
  def do_GET(self):
    self.send_response(200)
    self.send_header('Content-type', 'text/plain')
    self.end_headers()
    self.wfile.write(bytes('UP', 'utf8'))
    return

def generate_jwt():
  private_key = b64decode(GITHUB_APP_PRIVATE_KEY).decode('ascii')
  now = datetime.utcnow()
  payload = {
    'iat': now,
    'exp': now + timedelta(minutes=10),
    'iss': GITHUB_APP_ID
  }
  token = jwt.encode(payload, private_key, algorithm='RS256')
  return token

def get_access_token(jwt_token):
  headers = {
    'Authorization': f'Bearer {jwt_token}',
    'Accept': 'application/vnd.github.v3+json'
  }
  response = requests.post(
    f'https://api.github.com/app/installations/{GITHUB_APP_INSTALLATION_ID}/access_tokens',
    headers=headers
  )
  response.raise_for_status()
  return response.json()['token']

def update_sc_component(c_id, data):
  try:
    log.debug(data)
    x = requests.put(
      f'{SC_API_ENDPOINT}/v1/components/{c_id}',
      headers=sc_api_headers,
      json={'data': data},
      timeout=10,
    )
    if x.status_code == 200:
      log.info(f'Successfully updated component id {c_id}: {x.status_code}')
    else:
      log.info(
        f'Received non-200 response from service catalogue for component id {c_id}: {x.status_code} {x.content}'
      )
  except Exception as e:
    log.error(f'Error updating component in the SC: {e}')

def update_sc_product(p_id, data):
  try:
    log.debug(data)
    x = requests.put(
      f'{SC_PRODUCT_UPDATE_ENDPOINT}/{p_id}',
      headers=sc_api_headers,
      json={'data': data},
      timeout=10,
    )
    if x.status_code == 200:
      log.info(f'Successfully updated product id {p_id}: {x.status_code}')
    else:
      log.info(
        f'Received non-200 response from service catalogue for product id {p_id}: {x.status_code} {x.content}'
      )
  except Exception as e:
    log.error(f'Error updating product in the SC: {e}')

def get_file_yaml(repo, path):
  try:
    file_contents = repo.get_contents(path)
    contents = b64decode(file_contents.content).decode().replace('\t', '  ')
    yaml_contents = yaml.safe_load(contents)
    return yaml_contents
  except github.UnknownObjectException:
    log.debug(f'404 File not found {repo.name}:{path}')
  except Exception as e:
    log.error(f'Error getting yaml file: {e}')


def get_file_json(repo, path):
  try:
    file_contents = repo.get_contents(path)
    json_contents = json.loads(b64decode(file_contents.content))
    return json_contents
  except github.UnknownObjectException:
    log.debug(f'404 File not found {repo.name}:{path}')
  except Exception as e:
    log.error(f'Error getting json file: {e}')


def get_file_plain(repo, path):
  try:
    file_contents = repo.get_contents(path)
    plain_contents = b64decode(file_contents.content).decode()
    return plain_contents
  except github.UnknownObjectException:
    log.debug(f'404 File not found {repo.name}:{path}')
    return False
  except Exception as e:
    log.error(f'Error getting contents from file: {e}')


def test_endpoint(url, endpoint):
  headers = {'User-Agent': 'hmpps-service-discovery'}
  try:
    r = requests.get(
      f'{url}{endpoint}', headers=headers, allow_redirects=False, timeout=10
    )
    # Test if json is returned
    if r.json() and r.status_code != 404:
      log.debug(f'Found endpoint: {url}{endpoint} ')
      return True
  except Exception:
    log.debug(f'Could not connect to endpoint: {url}{endpoint} ')
    return False


def test_swagger_docs(url):
  headers = {'User-Agent': 'hmpps-service-discovery'}
  try:
    r = requests.get(
      f'{url}/swagger-ui.html', headers=headers, allow_redirects=False, timeout=10
    )
    # Test for 302 redirect)
    if r.status_code == 302 and (
      '/swagger-ui/index.html' in r.headers['Location']
      or 'api-docs/index.html' in r.headers['Location']
    ):
      log.debug(f'Found swagger docs: {url}/swagger-ui.html')
      return True
  except Exception:
    log.debug(f"Couldn't connect: {url}/swagger-ui.html")
    return False


def test_subject_access_request_endpoint(url):
  headers = {'User-Agent': 'hmpps-service-discovery'}
  try:
    r = requests.get(
      f'{url}/v3/api-docs', headers=headers, allow_redirects=False, timeout=10
    )
    if r.status_code == 200:
      try:
        if r.json()['paths']['/subject-access-request']:
          log.debug(f'Found SAR endpoint at: {url}/v3/api-docs')
          return True
      except KeyError:
        log.debug('No SAR endpoint found.')
        return False
  except TimeoutError:
    log.debug(f"Timed out connecting to: {url}/v3/api-docs")
    return False
  except Exception:
    log.debug(f"Couldn't connect: {url}/v3/api-docs {r.status_code}")
    return False


def get_sc_id(match_type, match_field, match_string):
  try:
    r = requests.get(
      f'{SC_API_ENDPOINT}/v1/{match_type}?filters[{match_field}][$eq]={match_string}',
      headers=sc_api_headers,
      timeout=10,
    )
    if r.status_code == 200 and r.json()['data']:
      sc_id = r.json()['data'][0]['id']
      log.info(
        f'Successfully found ID {sc_id}, matching type/field/string: {match_type}/{match_field}/{match_string}'
      )
      return sc_id
    log.info(
      f'Could not find ID, matching type/field/string: {match_type}/{match_field}/{match_string}'
    )
    return False
  except Exception as e:
    log.error(f'Error getting ID from SC: {e} - {r.status_code} {r.content}')
    return False


# This method is to find the values defined for allowlist in values*.yaml files under helm_deploy folder of each project.
# This methods read all the values files under helm_deploy folder and create a dictionary object of allowlist for each environment
# including the default values.


def fetch_values_for_allowlist_key(yaml_data, key):
  values = {}
  if isinstance(yaml_data, dict):
    if key in yaml_data:
      if isinstance(yaml_data[key], dict):
        values.update(yaml_data[key])
      else:
        values[key] = yaml_data[key]
    for k, v in yaml_data.items():
      if isinstance(v, (dict, list)):
        child_values = fetch_values_for_allowlist_key(v, key)
        if child_values:
          values.update({k: child_values})
  elif isinstance(yaml_data, list):
    for item in yaml_data:
      child_values = fetch_values_for_allowlist_key(item, key)
      if child_values:
        values.update(child_values)

  return values


# This method read the value stored in dictionary passed to it checks if the ip allow list is present or not and returns boolean


def is_ipallowList_enabled(yaml_data):
  ip_allow_list_enabled = False
  if isinstance(yaml_data, dict):
    for value in yaml_data.values():
      if isinstance(value, dict) and value:
        ip_allow_list_enabled = True
  return ip_allow_list_enabled


def get_trivy_scan_json_data(project_name):
  log.debug(f'Getting trivy scan data for {project_name}')
  circleci_headers = {
    'Circle-Token': CIRCLECI_TOKEN,
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  }
  project_url = f'{CIRCLECI_API_ENDPOINT}{project_name}'
  output_json_content = {}
  try:
    response = requests.get(project_url, headers=circleci_headers, timeout=30)
    for build_info in response.json():
      workflows = build_info.get('workflows', {})
      workflow_name = workflows.get('workflow_name', {})
      job_name = build_info.get('workflows', {}).get('job_name')
      if workflow_name == 'security' and job_name == 'hmpps/trivy_latest_scan':
        latest_build_num = build_info['build_num']
        artifacts_url = f'{project_url}/{latest_build_num}/artifacts'
        break
    log.debug(f'Getting artifact URLs from CircleCI')
    response = requests.get(artifacts_url, headers=circleci_headers, timeout=30)

    artifact_urls = response.json()
    output_json_url = next(
      (
        artifact['url']
        for artifact in artifact_urls
        if 'results.json' in artifact['url']
      ),
      None,
    )
    if output_json_url:
      log.debug(f'Fetching artifacts from CircleCI data')
      # do not use DEBUG logging for this request
      logging.getLogger("urllib3").setLevel(logging.INFO)     
      response = requests.get(
        output_json_url, headers=circleci_headers, timeout=30
      )
      logging.getLogger("urllib3").setLevel(LOG_LEVEL)     
      output_json_content = response.json()
    return output_json_content

  except Exception as e:
    log.debug(f'Error: {e}')


def get_slack_channel_name_by_id(slack_channel_id):
  log.debug(f'Getting Slack Channel Name for id {slack_channel_id}')
  slack_channel_name = None
  try:
    slack_channel_name = slack_client.conversations_info(channel=slack_channel_id)[
      'channel'
    ]['name']
  except SlackApiError as e:
    if 'channel_not_found' in str(e):
      log.info(
        f'Unable to update Slack channel name - {slack_channel_id} not found or private'
      )
    else:
      log.error(f'Slack error: {e}')
  log.debug(f'Slack channel name for {slack_channel_id} is {slack_channel_name}')      
  return slack_channel_name

def get_alertmanager_data():
  try:
    response = requests.get(ALERTMANAGER_ENDPOINT, verify=False)
    if response.status_code == 200:
      alertmanager_data = response.json()
      config_data = alertmanager_data['config']
      formatted_config_data = config_data["original"].replace('\\n', '\n')
      yaml_config_data = yaml.safe_load(formatted_config_data)
      json_config_data = json.loads(json.dumps(yaml_config_data))
      return json_config_data
    else:
      log.error(f"Error: {response.status_code}")
      return None
  except requests.exceptions.SSLError as e:
    log.error(f"SSL Error: {e}")
    return None
  except requests.exceptions.RequestException as e:
    log.error(f"Request Error: {e}")
    return None
  except json.JSONDecodeError as e:
    log.error(f"JSON Decode Error: {e}")
    return None

def find_channel_by_severity_label(alert_severity_label):
  # Find the receiver name for the given severity
  receiver_name = ''
  if alertmanager_json_data is None:
    return ''
  
  for route in alertmanager_json_data['route']['routes']:
    if route['match'].get('severity') == alert_severity_label:
      receiver_name = route['receiver']
      break         
  # Find the channel for the receiver name
  if receiver_name:
    for receiver in alertmanager_json_data['receivers']:
      if receiver['name'] == receiver_name:
        slack_configs = receiver.get('slack_configs', [])
        if slack_configs:
          return slack_configs[0].get('channel')
        else :
          return ''

def process_components(data):
  log.info(f'Processing batch of {len(data)} components...')
  for component in data:
    # Wait until the API limit is reset if we are close to the limit
    while core_rate_limit.remaining < 100:
      time_delta = datetime.now() - core_rate_limit.reset
      time_to_reset = time_delta.total_seconds()
      log.info(f'Github API rate limit {core_rate_limit}')
      log.info(
        f'Backing off for {time_to_reset} second, to avoid github API limits.'
      )
      sleep(time_to_reset)

    t_repo = threading.Thread(target=process_repo, kwargs=component, daemon=True)

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (MAX_THREADS - 1):
      log.debug(
        f'Active Threads={threading.active_count()}, Max Threads={MAX_THREADS}'
      )
      sleep(10)

    t_repo.start()
    component_name = component['attributes']['name']
    log.info(f'Started thread for {component_name}')

def process_repo(**component):
  allow_list_key = 'allowlist'
  c_name = component['attributes']['name']
  log.info(f'Processing component: {c_name}')
  c_id = component['id']
  github_repo = component['attributes']['github_repo']
  part_of_monorepo = component['attributes']['part_of_monorepo']
  project_dir = (
    (component['attributes']['path_to_project'] or c_name)
    if part_of_monorepo
    else '.'
  )
  helm_dir = (
    component['attributes']['path_to_helm_dir'] or f'{project_dir}/helm_deploy'
  )

  # Get github repo data and default branch to compare file based changes
  try:
    repo = gh.get_repo(f'ministryofjustice/{github_repo}')
  except Exception as e:
    log.error(f'Error with ministryofjustice/{c_name}, check github app has permissions to see it. {e}')
    
  try:
    default_branch = repo.get_branch(repo.default_branch)
  except Exception as e:
    log.error(f'Error with ministryofjustice/{c_name}, unable to get default branch. {e}')
  current_commit = {
    'sha': default_branch.commit.sha,
    'date_time': default_branch.commit.commit.committer.date.isoformat(),
  }

  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}
  helm_envs = {}
  environments = []
  versions_data = {}
  trivy_scan_summary = {}
  # CircleCI config
  cirlcleci_config = get_file_yaml(repo, '.circleci/config.yml')
  if cirlcleci_config:
    try:
      trivy_scan_json = get_trivy_scan_json_data(c_name)
      trivy_scan_date = trivy_scan_json.get('CreatedAt')
      trivy_scan_summary.update(
        {'trivy_scan_json': trivy_scan_json, 'trivy_scan_date': trivy_scan_date}
      )
      # Add trivy scan result to final data dict.
      data.update(
        {'trivy_scan_summary': trivy_scan_summary.get('trivy_scan_json')}
      )
      data.update(
        {
          'trivy_last_completed_scan_date': trivy_scan_summary.get(
            'trivy_scan_date'
          )
        }
      )
    except Exception:
      log.debug('Unable to get trivy scan results')

    try:
      cirleci_orbs = cirlcleci_config['orbs']
      for key, value in cirleci_orbs.items():
        if 'ministryofjustice/hmpps' in value:
          hmpps_orb_version = value.split('@')[1]
          versions_data.update({'circleci': {'hmpps_orb': hmpps_orb_version}})
          log.debug(f'hmpps orb version: {hmpps_orb_version}')
    except Exception:
      log.debug('No hmpps orb version found')

  try:
    helm_deploy = repo.get_contents(helm_dir, default_branch.commit.sha)
  except Exception as e:
    helm_deploy = False
    log.debug(f'helm_deploy folder: {e}')
  try:
    repo_env_list = repo.get_environments()
    print(f"repo_env_list.totalCount = ", repo_env_list.totalCount)
  except Exception as e:
    log.debug(f'helm_deploy folder: {e}')
  existing_envs = component['attributes']['environments']
  stored_commit_data = component['attributes']['latest_commit']

  # Compare the current commit SHA with the stored SHA
  if stored_commit_data.get('sha') != current_commit['sha'] or (not existing_envs and repo_env_list.totalCount > 0):
    log.info(f'Repo {github_repo} has changed since last service catalogue update.')

    # Helm charts
    if helm_deploy:
      helm_commits = repo.get_commits(path=helm_dir)
      latest_helm_dir_commit = helm_commits[0] if helm_commits.totalCount > 0 else None
      
      env_lookup = {env['name']: env for env in existing_envs}
      helm_values_data = {}
      if latest_helm_dir_commit:
        latest_helm_dir_commit_sha = latest_helm_dir_commit.sha  # Extracting the SHA value
        # Compare the current commit SHA with the stored SHA for the directory
        if stored_commit_data.get('sha') != latest_helm_dir_commit_sha:
          log.info(f'Directory {helm_dir} in repo {github_repo} has changed.')
          # Process the changed data
          helm_chart = (
            get_file_yaml(repo, f'{helm_dir}/{c_name}/Chart.yaml')
            or get_file_yaml(repo, f'{helm_dir}/Chart.yaml')
            or {}
          )
          if 'dependencies' in helm_chart:
            helm_dep_versions = {}
            for item in helm_chart['dependencies']:
              helm_dep_versions.update({item['name']: item['version']})
            versions_data.update({'helm_dependencies': helm_dep_versions})

          helm_environments = []
          helm_values_data = {}
          ip_allow_list_data = {}
          ip_allow_list = {}
          for file in helm_deploy:
            if file.name.startswith('values-'):
              env = re.match('values-([a-z0-9-]+)\\.y[a]?ml', file.name)[1]    
              helm_values_data[env] = get_file_yaml(repo, f'{helm_dir}/{file.name}')
              helm_environments.append(env)

              # HEAT-223 Start : Read and collate data for IPallowlist from all environment specific values.yaml files.
              ip_allow_list[file] = fetch_values_for_allowlist_key(get_file_yaml(repo, f'{helm_dir}/{file.name}'), allow_list_key)
              ip_allow_list_data.update({file.name: ip_allow_list[file]})
              # HEAT-223 End : Read and collate data for IPallowlist from all environment specific values.yaml files.

          helm_default_values = (
            get_file_yaml(repo, f'{helm_dir}/{c_name}/values.yaml')
            or get_file_yaml(repo, f'{helm_dir}/values.yaml')
            or {}
          )

          if helm_default_values:
            ip_allow_list_default = fetch_values_for_allowlist_key(helm_default_values, allow_list_key)
            # Try to get the container image
            try:
              container_image = helm_default_values['image']['repository']
              data.update({'container_image': container_image})
            except KeyError:
              pass
            try:
              container_image = helm_default_values['generic-service']['image'][
                'repository'
              ]
              data.update({'container_image': container_image})
            except KeyError:
              pass
            # Try to get the productID
            try:
              product_id = helm_default_values['generic-service']['productId']
              sc_product_id = get_sc_id('products', 'p_id', product_id)
              if sc_product_id:
                data.update({'product': sc_product_id})
            except KeyError:
              pass

            # Get modsecurity data, if enabled.
            modsecurity_enabled_default = None
            modsecurity_audit_enabled_default = None
            modsecurity_snippet_default = None
            try:
              modsecurity_enabled_default = helm_default_values['generic-service']['ingress']['modsecurity_enabled']
            except KeyError:
              pass

            try:
              modsecurity_audit_enabled_default = helm_default_values['generic-service']['ingress']['modsecurity_audit_enabled']
            except KeyError:
              pass

            try:
              modsecurity_snippet_default = helm_default_values['generic-service']['ingress']['modsecurity_snippet']
            except KeyError:
              pass

            try:
              default_alert_severity_label = helm_default_values['generic-prometheus-alerts']['alertSeverity']
            except KeyError:
              pass

          # helm env values files, extract useful values

          for env in helm_environments:
            allow_list_values = {}
            e = {}

            # environment type can be dev, test, stage, preprod, prod
            if env.lower() == 'staging' or env.lower() == 'uat' or env.lower() == 'stage' or env.lower() == 'test':
              env_type = 'stage'
            elif env.lower() == 'demo':
              env_type = 'test'
            elif env.lower() == 'dev' or env.lower() == 'development':
              env_type = 'dev'
            elif env.lower() == 'preprod' or env.lower() == 'preproduction':
              env_type = 'preprod'
            elif env.lower() == 'production' or env.lower() == 'prod':
              env_type = 'prod'

            if env in env_lookup: # Update existing environment
              env_id = env_lookup[env]['id']
              e.update({'id': env_id})
            else:
              print("env not in env_lookup")
              e.update({'name': env, 'type': env_type})
              try:
                log.info(f'Creating new environment {env} for {c_name}')
                repo_env_set = {env.name for env in repo_env_list}
                if env in repo_env_set or env_type in repo_env_set:
                  repo_env_data = repo.get_environment(env)
                  print(f"repo_env_data = ", repo_env_data)
                  env_vars = repo_env_data.get_variables()
                  print(f"env_vars = ", env_vars)
                  for var in env_vars:
                    if var.name == 'KUBE_NAMESPACE':
                      kube_namespace = var.value
                      e.update({'namespace': kube_namespace})
                      ns_id = get_sc_id('namespaces', 'name', kube_namespace)
                      if ns_id:
                        e.update({'ns': ns_id})
              except Exception as e:
                log.error(f'Error with ministryofjustice/{c_name}, unable to get environments variable KUBE_NAMESPACE. {e}')

            values = helm_values_data[env]
            if values:
              # Ingress hostname
              try:
                host = values['generic-service']['ingress']['host']
                helm_envs.update({env: {'host': host}})
                log.debug(f'{env} ingress host: {host}')
              except KeyError:
                pass
              # Ingress alternative location
              try:
                host = values['generic-service']['ingress']['hosts'][-1]
                helm_envs.update({env: {'host': host}})
                log.debug(f'{env} ingress host: {host}')
              except KeyError:
                pass
              # Ingress alternative location
              try:
                host = values['ingress']['host']
                helm_envs.update({env: {'host': host}})
                log.debug(f'{env} ingress host: {host}')
              except KeyError:
                pass
              # Ingress alternative location
              try:
                host = values['ingress']['hosts'][-1]['host']
                helm_envs.update({env: {'host': host}})
                log.debug(f'{env} ingress host: {host}')
              except KeyError:
                pass
              # Container image alternative location
              try:
                container_image = values['image']['repository']
                data.update({'container_image': container_image})
              except KeyError:
                pass
              try:
                container_image = values['generic-service']['image']['repository']
                data.update({'container_image': container_image})
              except KeyError:
                pass

            env_url = f'https://{helm_envs[env]["host"]}'
            if env_url:
              health_path = '/health'
              info_path = '/info'
              # Hack for hmpps-auth non standard endpoints
              if 'sign-in' in env_url:
                health_path = '/auth/health'
                info_path = '/auth/info'
              if test_endpoint(env_url, health_path):
                e.update({'health_path': health_path})
              if test_endpoint(env_url, info_path):
                e.update({'info_path': info_path})
              # Test for API docs - and if found also test for SAR endpoint.
              if test_swagger_docs(env_url):
                e.update({'swagger_docs': '/swagger-ui.html'})
                data.update({'api': True, 'frontend': False})
                if test_subject_access_request_endpoint(env_url):
                  e.update({'include_in_subject_access_requests': True})
                else:
                  e.update({'include_in_subject_access_requests': False})

            try:
              ip_allow_list_env = ip_allow_list_data[f'values-{env}.yaml']
              allow_list_values.update(
                {
                  f'values-{env}.yaml': ip_allow_list_env,
                  'values.yaml': ip_allow_list_default,
                }
              )
              e.update(
                {
                  'ip_allow_list': allow_list_values,
                  'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values),
                }
              )
            except KeyError:
              pass

            # Get modsecurity data
            modsecurity_enabled_env = None
            modsecurity_audit_enabled_env = None
            modsecurity_snippet_env = None
            try:
              print(values['generic-service']['ingress']['modsecurity_enabled'])
              modsecurity_enabled_env = values['generic-service']['ingress']['modsecurity_enabled']
            except KeyError:
              pass
            try:
              print(values['generic-service']['ingress']['modsecurity_audit_enabled'])
              modsecurity_audit_enabled_env = values['generic-service']['ingress']['modsecurity_audit_enabled']
            except KeyError:
              pass
            try:
              print(values['generic-service']['ingress']['modsecurity_snippet'])
              modsecurity_snippet_env = values['generic-service']['ingress']['modsecurity_snippet']
            except KeyError:
              pass
            if modsecurity_enabled_env is None and modsecurity_enabled_default:
              e.update({'modsecurity_enabled': True})
            elif modsecurity_enabled_env:
              e.update({'modsecurity_enabled': True})
            else:
              e.update({'modsecurity_enabled': False})

            if (
              modsecurity_audit_enabled_env is None
              and modsecurity_audit_enabled_default
            ):
              e.update({'modsecurity_audit_enabled': True})
            elif modsecurity_enabled_env:
              e.update({'modsecurity_audit_enabled': True})
            else:
              e.update({'modsecurity_audit_enabled': False})

            if modsecurity_snippet_env is None and modsecurity_snippet_default:
              e.update({'modsecurity_snippet': modsecurity_snippet_default})
            elif modsecurity_snippet_env:
              e.update({'modsecurity_snippet': modsecurity_snippet_env})
            else:
              e.update({'modsecurity_snippet': None})
            # build_image_tag in environment is populated by hmpps-health-ping

            # Alert severity label
            alert_severity_label = None
            try:
              alert_severity_label = values['generic-prometheus-alerts']['alertSeverity']
            except KeyError:
              alert_severity_label = default_alert_severity_label
            if alert_severity_label:
              channel = find_channel_by_severity_label(alert_severity_label)
              e.update({'alert_severity_label': alert_severity_label})
              e.update({'alerts_slack_channel': channel})
            environments.append(e)
      else:
        log.info(f'Directory {helm_dir} in repo {github_repo} has not changed.')
    else:
      log.info(f'No commits found for directory {helm_dir} in repo {github_repo}.')
    # End of helm chart processing
    
    # App insights cloud_RoleName
    if repo.language == 'Kotlin' or repo.language == 'Java':
      app_insights_config = get_file_json(
        repo, f'{project_dir}/applicationinsights.json'
      )
      if app_insights_config:
        app_insights_cloud_role_name = app_insights_config['role']['name']
        data.update({'app_insights_cloud_role_name': app_insights_cloud_role_name})

    if repo.language == 'JavaScript' or repo.language == 'TypeScript':
      package_json = get_file_json(repo, f'{project_dir}/package.json')
      if package_json:
        app_insights_cloud_role_name = package_json['name']
        if re.match(r'^[a-zA-Z0-9-_]+$', app_insights_cloud_role_name):
          data.update(
            {'app_insights_cloud_role_name': app_insights_cloud_role_name}
          )

    # Gradle config
    build_gradle_config_content = False
    if repo.language == 'Kotlin' or repo.language == 'Java':
      build_gradle_kts_config = get_file_plain(repo, 'build.gradle.kts')
      build_gradle_config_content = build_gradle_kts_config
    # Try alternative location for java projects
    if not build_gradle_config_content:
      build_gradle_java_config = get_file_plain(repo, 'build.gradle')
      build_gradle_config_content = build_gradle_java_config

    if build_gradle_config_content:
      try:
        regex = "id\\(\\'uk.gov.justice.hmpps.gradle-spring-boot\\'\\) version \\'(.*)\\'( apply false)?$"
        hmpps_gradle_spring_boot_version = re.search(
          regex, build_gradle_config_content, re.MULTILINE
        )[1]
        log.debug(
          f'Found hmpps gradle-spring-boot version: {hmpps_gradle_spring_boot_version}'
        )
        versions_data.update(
          {
            'gradle': {
              'hmpps_gradle_spring_boot': hmpps_gradle_spring_boot_version
            }
          }
        )
      except TypeError:
        pass

    # Parse Dockerfile
    try:
      file_contents = repo.get_contents(f'{project_dir}/Dockerfile')
      dockerfile = DockerfileParser(fileobj=tempfile.NamedTemporaryFile())
      dockerfile.content = b64decode(file_contents.content)

      docker_data = {}
      if re.search(r'rds-ca-2019-root\.pem', dockerfile.content, re.MULTILINE):
        docker_data.update({'rds_ca_cert': 'rds-ca-2019-root.pem'})
      if re.search(r'global-bundle\.pem', dockerfile.content, re.MULTILINE):
        docker_data.update({'rds_ca_cert': 'global-bundle.pem'})

      try:
        # Get list of parent images, and strip out references to 'base'
        parent_images = list(
          filter(lambda i: i != 'base', dockerfile.parent_images)
        )
        # Get the last element in the array, which should be the base image of the final stage.
        base_image = parent_images[-1]
        docker_data.update({'base_image': base_image})
        log.debug(f'Found Dockerfile base image: {base_image}')
      except Exception as e:
        log.error(f'Error parent/base image from Dockerfile: {e}')

      if docker_data:
        versions_data.update({'dockerfile': docker_data})

    except github.UnknownObjectException:
      log.info(f'404 File not found {repo.name}:Dockerfile')
    except Exception as e:
      log.error(f'Error parsing Dockerfile: {e}') 

  else:
    log.info(f'Repo {github_repo} has not changed, file based changes ignored.')

  # If no environment data is discovered above, and if environment data has been
  # manually added to the SC, ensure we just pass the existing data to the SC update.
  if not environments:
    environments = component['attributes']['environments']

  # Add Environments to final data dict
  data.update({'environments': environments})

  # Add versions to final data dict.
  data.update({'versions': versions_data})
  
  # Below code is for updating the service catalogue with the latest data which does not affect repo sha changes
  data.update({'language': repo.language})
  data.update({'description': repo.description})
  data.update({'github_project_visibility': repo.visibility})
  data.update({'github_repo': repo.name})
  data.update({'latest_commit': {
    'sha': default_branch.commit.sha,
    'date_time': default_branch.commit.commit.committer.date.isoformat(),
  }})

  # GitHub teams access, branch protection etc.
  branch_protection_restricted_teams = []
  teams_write = []
  teams_admin = []
  teams_maintain = []
  try:
    branch_protection = default_branch.get_protection()
    branch_protection_teams = branch_protection.get_team_push_restrictions() or []
    for team in branch_protection_teams:
      branch_protection_restricted_teams.append(team.slug)
  except Exception as e:
    log.error(f'Unable to get branch protection {repo.name}: {e}')

  teams = repo.get_teams()
  for team in teams:
    team_permissions = team.get_repo_permission(repo)
    if team_permissions.admin:
      teams_admin.append(team.slug)
    elif team_permissions.maintain:
      teams_maintain.append(team.slug)
    elif team_permissions.push:
      teams_write.append(team.slug)
  data.update({'github_project_teams_admin': teams_admin})
  log.debug(f'teams_admin: {teams_admin}')
  data.update({'github_project_teams_maintain': teams_maintain})
  log.debug(f'teams_maintain: {teams_maintain}')
  data.update({'github_project_teams_write': teams_write})
  log.debug(f'teams_write: {teams_write}')
  data.update({'github_project_branch_protection_restricted_teams': branch_protection_restricted_teams})
  log.debug(f'branch_protection_restricted_teams: {branch_protection_restricted_teams}')

  # Get enforce_admin details from branch protection
  enforce_admins = branch_protection.enforce_admins
  data.update({'github_enforce_admins_enabled': enforce_admins})
  log.debug(f'github_enforce_admins_enabled: {enforce_admins}')
        
  # Github topics
  topics = repo.get_topics()
  data.update({'github_topics': topics})
  # Update component with all results in data dict.
  update_sc_component(c_id, data)


# This does the same as the component update process, but with the product API
def process_repo_product(**product):

  p_name = product['attributes']['name']
  p_id = product['id']

  log.info(f'Processing product: {p_name}')

  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}

  # Update Slack Channel name if necessary:
  p_slack_channel_id = product['attributes']['slack_channel_id']
  p_slack_channel_name = product['attributes']['slack_channel_name']
  if p_slack_channel_id != '':
    slack_channel_name = get_slack_channel_name_by_id(p_slack_channel_id)
    if slack_channel_name and p_slack_channel_name != slack_channel_name:
      data.update({'slack_channel_name': slack_channel_name})

  if data:
    # Update product with all results in data dict.
    update_sc_product(p_id, data)

def startHttpServer():
  handler_object = HealthHttpRequestHandler
  with socketserver.TCPServer(('', 8080), handler_object) as httpd:
    httpd.serve_forever()

def extract_teams(terraform_content):
    parent_teams_pattern = re.compile(r'parent_teams\s*=\s*\[(.*?)\]', re.DOTALL)
    sub_teams_pattern = re.compile(r'sub_teams\s*=\s*\[(.*?)\]', re.DOTALL)
    team_pattern = re.compile(r'\{\s*name\s*=\s*"([^"]+)"\s*parent\s*=\s*"([^"]+)"\s*description\s*=\s*"([^"]+)"\s*\}')

    parent_teams_match = parent_teams_pattern.search(terraform_content)
    sub_teams_match = sub_teams_pattern.search(terraform_content)

    parent_teams = []
    sub_teams = []

    if parent_teams_match:
        parent_teams_content = parent_teams_match.group(1)
        parent_teams = team_pattern.findall(parent_teams_content)

    if sub_teams_match:
        sub_teams_content = sub_teams_match.group(1)
        sub_teams = team_pattern.findall(sub_teams_content)

    combined_teams = parent_teams + sub_teams
    return combined_teams

def find_github_team(teams_json_data, team_name):
    for item in teams_json_data.get('data', []):
        if item['attributes'].get('team_name') == team_name:
            return item
    return None

def insert_github_team(teams_json_data, team_id, team_name, team_parent, team_description, members, terraform_managed):
    c_team = find_github_team(teams_json_data, team_name)
    check_team = c_team.get('attributes', {}) if c_team else {}
    c_team_id = c_team.get('id', None) if c_team else None
    team_data = {
      'github_team_id': team_id,
      'team_name': team_name,
      'parent_team_name': team_parent,
      'team_desc': team_description,
      'members': members,
      'terraform_managed': terraform_managed,
    }
    if c_team_id:
      if check_team['github_team_id'] != team_id or check_team['team_desc'] != team_description or check_team['parent_team_name'] != team_parent or check_team['members'] != members or check_team['terraform_managed'] != terraform_managed: 
        # Update the team in SC
        x = requests.put(
          f'{SC_API_ENDPOINT}/v1/github-teams/{c_team_id}',
          headers=sc_api_headers,
          json={'data': team_data},
          timeout=10,
        )
        if x.status_code == 200:
          log.info(f'Successfully updated team {team_name}: {x.status_code}')
        else:
          log.info(
            f'Received non-200 response from service catalogue for updating team {team_name}: {x.status_code} {x.content}'
          )
    else:
      # Create the team in SC
      x = requests.post(
        f'{SC_API_ENDPOINT}/v1/github-teams',
        headers=sc_api_headers,
        json={'data': team_data},
        timeout=10,
      )
      if x.status_code == 200:
        log.info(f'Successfully added team {team_name}: {x.status_code}')
      else:
        log.info(
          f'Received non-200 response from service catalogue for team {team_name}: {x.status_code} {x.content}'
        )

def get_github_teams_data():
  try:
    r = requests.get(SC_ENDPOINT_TEAMS, headers=sc_api_headers, timeout=10)
    log.debug(r.json())
    return r.json()
  except Exception as e:
    log.error(f'Error getting team in the SC: {e}')
    return False

def process_terraform_managed_teams(teams_json_data):
  log.info(f'Processing teams in function...')
  teamrepo = gh.get_repo('ministryofjustice/hmpps-github-teams')
  team_contents = teamrepo.get_contents('terraform/teams.tf')
  team_file = base64.b64decode(team_contents.content).decode('utf-8')
  tf_data = extract_teams(team_file)
  log.info(f'Found {len(tf_data)} teams in the terraform file')
  teams = org.get_teams()
  team_id_map = {team.name: team.id for team in teams}

  for team in tf_data:
    team_name = team[0]
    team_parent = team[1]
    team_description = team[2]
    team_id = team_id_map.get(team_name, "Unknown ID")
    members = [member.login for member in org.get_team(team_id).get_members()]
    terraform_managed = True
    insert_github_team(teams_json_data,team_id, team_name, team_parent, team_description, members, terraform_managed)
  return None

def process_non_terraform_managed_teams(teams_json_data):
  log.info(f'Processing Teams not managed by terraform...')
  try:
    r = requests.get(SC_ENDPOINT_COMPONENTS, headers=sc_api_headers, timeout=10)
    log.debug(r)
  except Exception as e:
    log.error(f'Error getting components from the SC: {e}')
    return False
  components = r.json().get('data', [])
  combined_teams = set()
  for component in components:
    attributes = component.get('attributes', {})
    combined_teams.update(attributes.get('github_project_teams_write', []) or [])
    combined_teams.update(attributes.get('github_project_teams_admin', []) or [])
    combined_teams.update(attributes.get('github_project_teams_maintain', []) or [])

  print("Teams not in Terraform: ", combined_teams)
  log.info(f'Found {len(combined_teams)} unique teams referenced in the SC for components')

  existing_teams = {team['attributes']['team_name'] for team in teams_json_data.get('data', [])}
  for team_name in combined_teams:
    if team_name not in existing_teams:
      try:
        team = org.get_team_by_slug(team_name)
        team_id = team.id
        team_parent = team.parent.name if team.parent else None
        team_description = team.description
        members = [member.login for member in org.get_team(team_id).get_members()]
      except Exception as e:
        log.error(f'Error getting team data from GitHub for {team_name}: {e}')
        continue
      terraform_managed = False
      insert_github_team(teams_json_data,team_id, team_name, team_parent, team_description, members, terraform_managed)
  return None

def process_products(data):
  log.info(f'Processing batch of {len(data)} products...')
  for product in data:
    t_repo = threading.Thread(
      target=process_repo_product, kwargs=product, daemon=True
    )

    # Slack rate limits in esoteric ways. Hopefully 10 threads is fine
    # https://api.slack.com/apis/rate-limits#tiers
    while threading.active_count() > (MAX_THREADS - 1):
      log.debug(
        f'Active Threads={threading.active_count()}, Max Threads={MAX_THREADS}'
      )
      sleep(5)

    t_repo.start()
    product_name = product['attributes']['name']
    p_id = product['attributes']['p_id']
    log.info(f'Started thread for {p_id} ({product_name})')


################# Main functions #################

if __name__ == '__main__':
  logging.basicConfig(format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=LOG_LEVEL)
  log = logging.getLogger(__name__)
  sc_api_headers = {
    'Authorization': f'Bearer {SC_API_TOKEN}',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  }

  # Test connection to Service Catalogue
  try:
    r = requests.head(
      f'{SC_API_ENDPOINT}/_health', headers=sc_api_headers, timeout=10
    )
    log.info(f'Successfully connected to the Service Catalogue. {r.status_code}')
  except Exception as e:
    log.critical('Unable to connect to the Service Catalogue.')
    raise SystemExit(e) from e

  # Test auth and connection to github
  try:
    jwt_token = generate_jwt()
    access_token = get_access_token(jwt_token) # Token is valid only for 30 mins so we need to re-authenticate every 30 mins
    auth = Auth.Token(access_token) 
    gh = Github(auth=auth, pool_size=50)
    org=gh.get_organization('ministryofjustice')
    rate_limit = gh.get_rate_limit()
    core_rate_limit = rate_limit.core
    log.info(f'Github API: {rate_limit}')
  except Exception as e:
    log.critical('Unable to connect to the github API.')
    raise SystemExit(e) from e

  # Test auth and connection to Slack
  try:
    log.debug(f'Connecting to Slack with token ending {SLACK_BOT_TOKEN[:-4]}')
    slack_client = WebClient(token=SLACK_BOT_TOKEN)
    test_api = slack_client.api_test()
    log.info('Successfully conected to Slack.')
  except Exception as e:
    log.critical('Unable to connect to Slack.')
    raise SystemExit(e) from e

  # Main loop
  while True:
    # Start health endpoint.
    httpHealth = threading.Thread(target=startHttpServer, daemon=True)
    httpHealth.start()

    # Get alertmanager data
    alertmanager_json_data = get_alertmanager_data()
    # print(alertmanager_json_data)

    # Process components
    log.info(SC_ENDPOINT)
    try:
      r = requests.get(SC_ENDPOINT, headers=sc_api_headers, timeout=10)
      log.debug(r)
      if r.status_code == 200:
        j_meta = r.json()['meta']['pagination']
        log.debug(f'Got result page: {j_meta["page"]} from SC')
        j_data = r.json()['data']
        process_components(j_data)
      else:
        raise Exception(
          f'Received non-200 response from Service Catalogue: {r.status_code}'
        )

      # Loop over the remaining pages and return one at a time
      num_pages = j_meta['pageCount']
      for p in range(2, num_pages + 1):
        page = f'&pagination[page]={p}'
        r = requests.get(
          f'{SC_ENDPOINT}{page}', headers=sc_api_headers, timeout=10
        )
        if r.status_code == 200:
          j_meta = r.json()['meta']['pagination']
          log.debug(f'Got result page: {j_meta["page"]} from SC')
          j_data = r.json()['data']
          process_components(j_data)
        else:
          raise Exception(
            f'Received non-200 response from Service Catalogue: {r.status_code}'
          )

    except Exception as e:
      log.error(
        f'Problem with Service Catalogue API while processing components. {e}'
      )

    # Process Teams
    log.info('Processing teams...')
    teams_json_data = get_github_teams_data()
    process_terraform_managed_teams(teams_json_data)
    process_non_terraform_managed_teams(teams_json_data)

    # Process products
    log.info(SC_PRODUCT_ENDPOINT)
    try:
      r = requests.get(SC_PRODUCT_ENDPOINT, headers=sc_api_headers, timeout=10)
      log.debug(r)
      if r.status_code == 200:
        j_meta = r.json()['meta']['pagination']
        log.debug(f'Got result page: {j_meta["page"]} from SC')
        j_data = r.json()['data']
        process_products(j_data)
      else:
        raise Exception(
          f'Received non-200 response from Service Catalogue: {r.status_code}'
        )

      # Loop over the remaining pages and return one at a time
      num_pages = j_meta['pageCount']
      for p in range(2, num_pages + 1):
        page = f'&pagination[page]={p}'
        r = requests.get(
          f'{SC_PRODUCT_ENDPOINT}{page}', headers=sc_api_headers, timeout=10
        )
        if r.status_code == 200:
          j_meta = r.json()['meta']['pagination']
          log.debug(f'Got result page: {j_meta["page"]} from SC')
          j_data = r.json()['data']
          process_products(j_data)
        else:
          raise Exception(
            f'Received non-200 response from Service Catalogue: {r.status_code}'
          )

    except Exception as e:
      log.error(
        f'Problem with Service Catalogue API while processing products. {e}'
      )
    log.info(f'All done - sleeping for {REFRESH_INTERVAL_HOURS} hours')
    sleep((REFRESH_INTERVAL_HOURS * 60 * 60))
    log.info('Waking up...')
    try:
      jwt_token = generate_jwt()
      access_token = get_access_token(jwt_token) # Token is valid only for 30 mins so we need to re-authenticate every 30 mins
      auth = Auth.Token(access_token) 
      gh = Github(auth=auth, pool_size=50)
      org=gh.get_organization('ministryofjustice')
      rate_limit = gh.get_rate_limit()
      core_rate_limit = rate_limit.core
      log.info(f'Github API: {rate_limit}')
    except Exception as e:
      log.critical('Unable to connect to the github API.')
      raise SystemExit(e) from e

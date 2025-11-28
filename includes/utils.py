import requests

# hmpps
from hmpps.services.job_log_handling import (
  log_debug,
  log_info,
)


# Various endoint tests
def test_endpoint(url, endpoint):
  headers = {'User-Agent': 'hmpps-service-discovery'}
  try:
    r = requests.get(
      f'{url}{endpoint}', headers=headers, allow_redirects=False, timeout=10
    )
    # Test if json is returned
    if r.json() and r.status_code != 404:
      log_debug(f'Found endpoint: {url}{endpoint} ')
      return True
  except Exception as e:
    log_info(f'Could not connect to endpoint {url}{endpoint} - {e}')
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
      log_debug(f'Found swagger docs: {url}/swagger-ui.html')
      return True
  except Exception as e:
    log_debug(f"Couldn't connect to {url}/swagger-ui.html - {e}")
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
          log_debug(f'Found SAR endpoint at: {url}/v3/api-docs')
          return True
      except KeyError:
        log_debug('No SAR endpoint found.')
        return False
  except TimeoutError:
    log_debug(f'Timed out connecting to: {url}/v3/api-docs')
    return False
  except Exception as e:
    log_debug(f"Couldn't connect to {url}/v3/api-docs: {e}")
    return False


# This method read the value stored in dictionary passed to it checks if the ip allow list is present or not and returns boolean
def is_ipallowList_enabled(yaml_data):
  ip_allow_list_enabled = False
  if isinstance(yaml_data, dict):
    for value in yaml_data.values():
      if isinstance(value, dict) and value:
        ip_allow_list_enabled = True
  return ip_allow_list_enabled


################################################################################################
# get_existing_env_config
# This function will get the config value from the component environment
# to prevent it being overwritten by blank entries
def get_existing_env_config(component, env_name, config, services):
  config_value = None
  if envs := component.get('envs', {}):
    env_data = next(
      (env for env in envs if env.get('name') == env_name),
      {},
    )
    if config_value := env_data.get(config):
      log_debug(f'Existing config: {config}, {config_value}')
    else:
      log_debug(f'No existing value found for {config}')

  return config_value


def remove_version(data, version):
  log_debug(f'attempting to remove {version} from data["versions"]')
  if versions := data.get('versions', {}):
    if version in versions:
      log_debug(f'found {version}')
      versions.pop(version)

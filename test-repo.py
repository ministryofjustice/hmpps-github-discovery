#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue

Required environment variables
------------------------------

Alertmanager
- ALERTMANAGER_ENDPOINT: Alertmanager API endpoint

Github (Credentials for Discovery app that has access to the repositories)
- GITHUB_APP_ID: Github App ID
- GITHUB_APP_INSTALLATION_ID: Github App Installation ID
- GITHUB_APP_PRIVATE_KEY: Github App Private Key

Service Catalogue
- SERVICE_CATALOGUE_API_ENDPOINT: Service Catalogue API endpoint
- SERVICE_CATALOGUE_API_KEY: Service

- SLACK_BOT_TOKEN: Slack Bot Token

- CIRCLECI_API_ENDPOINT: CircleCI API endpoint
- CIRCLECI_TOKEN: CircleCI API token

Optional environment variables
- SLACK_NOTIFY_CHANNEL: Slack channel for notifications
- SLACK_ALERT_CHANNEL: Slack channel for alerts
- LOG_LEVEL: Log level (default: INFO)

"""

import os
import argparse
import json

# Classes for the various parts of the script
# from classes.health import HealthServer
from classes.service_catalogue import ServiceCatalogue
from classes.github import GithubSession

# Components
import processes.workflows as workflows

# Standards
from utilities.job_log_handling import log_debug, log_error, log_info, log_warning

# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
max_threads = 10


class Services:
  def __init__(self, sc_params, gh_params):
    self.sc = ServiceCatalogue(sc_params)
    self.gh = GithubSession(gh_params)


###########################################################################################################
# Single component discovery
###########################################################################################################
def main():
  parser = argparse.ArgumentParser(description='Process a component.')
  parser.add_argument('component_name', help='The name of the component')
  args = parser.parse_args()
  component_name = args.component_name

  # service catalogue parameters
  sc_params = {
    'url': os.getenv('SERVICE_CATALOGUE_API_ENDPOINT'),
    'key': os.getenv('SERVICE_CATALOGUE_API_KEY'),
    'filter': os.getenv('SC_FILTER', ''),
  }

  # Github parameters
  gh_params = {
    'app_id': int(os.getenv('GITHUB_APP_ID')),
    'app_installation_id': int(os.getenv('GITHUB_APP_INSTALLATION_ID')),
    'app_private_key': os.getenv('GITHUB_APP_PRIVATE_KEY'),
  }

  services = Services(sc_params, gh_params)

  component = services.sc.get_record(services.sc.components_get, 'name', component_name)
  log_debug(f'Component: {component}')
  if component:
    repo_name = component.get('attributes').get('github_repo')
    log_info(f'Getting workflow business for {repo_name}')
    repo = services.gh.get_org_repo(repo_name)
    log_info(f'repo name: {repo.name}')
    # enter your process here
  else:
    log_error(f'Component {component_name} not found')

  # environments bits
  # environments = services.sc.get_all_records('environments?populate=component')
  # env_list = []
  # for env in environments:
  #   attrs = env.get('attributes', {})
  #   env_list.append(
  #     f'{attrs.get("component", {}).get("data", {}).get("attributes", {}).get("name")}-{
  #       attrs.get("name")
  #     }'
  #   )

  # env_list.sort()

  # for env in env_list:
  #   log_debug(f'{env}')

  # for item in env_list:
  #   if env_list.count(item) > 1:
  #     log_debug(f'{item}: {env_list.count(item)}')


if __name__ == '__main__':
  main()

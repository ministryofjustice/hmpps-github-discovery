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

# hmpps
from hmpps import ServiceCatalogue, GithubSession, AlertmanagerData, CircleCI
from hmpps.services.job_log_handling import log_debug, log_error, log_info


# local
import processes.components as components

# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
max_threads = 10


class Services:
  def __init__(self, sc_params, gh_params, am_params, cc_params):
    self.sc = ServiceCatalogue(sc_params)
    self.gh = GithubSession(gh_params)
    self.am = AlertmanagerData(am_params)
    self.cc = CircleCI(cc_params)


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
    'app_id': int(os.getenv('GITHUB_APP_ID', '0')),
    'app_installation_id': int(os.getenv('GITHUB_APP_INSTALLATION_ID', '0')),
    'app_private_key': os.getenv('GITHUB_APP_PRIVATE_KEY', ''),
  }

  cc_params = {
    'url': os.getenv(
      'CIRCLECI_API_ENDPOINT',
      'https://circleci.com/api/v1.1/project/gh/ministryofjustice/',
    ),
    'token': os.getenv('CIRCLECI_TOKEN'),
  }

  am_params = {
    'url': os.getenv(
      'ALERTMANAGER_ENDPOINT',
      'http://monitoring-alerts-service.cloud-platform-monitoring-alerts:8080/alertmanager/status',
    )
  }

  services = Services(sc_params, gh_params, am_params, cc_params)

  component = services.sc.get_record(services.sc.components_get, 'name', component_name)
  log_debug(f'Component: {component}')

  if not component:
    log_error(f'Component {component_name} not found')
    return

  if component.get('archived'):
    log_info(f'Component {component_name} is archived, skipping')
    return

  log_info(f'Processing component {component_name}...')
  processed_components = components.process_sc_component(
    component,
    services,
    components.get_bootstrap_projects(services),
    force_update=True,
  )
  log_info(f'Processed component: {processed_components}')


if __name__ == '__main__':
  main()

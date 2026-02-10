#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services
and stores the results in the service catalogue

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

# Set maximum number of concurrent threads to run, try to avoid
# secondary github api limits.
max_threads = 10


class Services:
  def __init__(self):
    self.sc = ServiceCatalogue()
    self.gh = GithubSession()
    self.am = AlertmanagerData()
    self.cc = CircleCI()


#######################################################################################
# Single component discovery
#######################################################################################
def main():
  parser = argparse.ArgumentParser(description='Process a component.')
  parser.add_argument('component_name', help='The name of the component')
  args = parser.parse_args()
  component_name = args.component_name

  services = Services()

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
    services,
    component,
    components.get_bootstrap_projects(services),
    force_update=True,
  )
  log_info(f'Processed component: {processed_components}')


if __name__ == '__main__':
  main()

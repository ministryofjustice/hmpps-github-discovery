#!/usr/bin/env python

import os
import argparse

# Classes for the various parts of the script
# from classes.health import HealthServer
from classes.service_catalogue import ServiceCatalogue
from classes.github import GithubSession

# Components
import processes.components as components
from utilities.job_log_handling import log_debug, log_error, log_info, log_critical

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
    log_info(f'Processing component {component_name}...')
    repo = services.gh.get_org_repo(component.get('github_repo'))
    github_actions = services.gh.get_actions(repo)
    log_debug(f'github_actions: {github_actions}')
  else:
    log_error(f'Component {component_name} not found')


if __name__ == '__main__':
  main()

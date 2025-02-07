#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue"""

import os
import logging

# Classes for the various parts of the script
# from classes.health import HealthServer
from classes.service_catalogue import ServiceCatalogue
from classes.github import GithubSession
from classes.slack import Slack
from classes.alertmanager import AlertmanagerData
from classes.circleci import CircleCI

# Components
import processes.github_teams as github_teams
import processes.products as products
import processes.components as components

# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
max_threads = 10
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()


class Services:
  def __init__(self, sc_params, gh_params, am_params, cc_params, slack_params, log):
    self.slack = Slack(slack_params, log)
    self.sc = ServiceCatalogue(sc_params, log)
    self.gh = GithubSession(gh_params, log)
    self.am = AlertmanagerData(am_params, log)
    self.cc = CircleCI(cc_params, log_level)
    self.log = log


def create_summary(services, processed_components, processed_products, processed_teams):
  qty_components = len(processed_components)
  qty_components_env_changed = len(
    [c for c in processed_components if c[1].get('env_changed')]
  )
  qty_components_main_changed = len(
    [c for c in processed_components if c[1].get('main_changed')]
  )
  components_update_error = [
    c for c in processed_components if c[1].get('update_error')
  ]

  components_not_found = [c for c in processed_components if c[1].get('not_found')]
  components_app_disabled = [
    c for c in processed_components if c[1].get('app_disabled')
  ]
  components_branch_protection_disabled = [
    c for c in processed_components if c[1].get('branch_protection_disabled')
  ]

  qty_environments_added = len(
    [c for c in processed_components if c[1].get('env_added')]
  )
  qty_environments_updated = len(
    [c for c in processed_components if c[1].get('env_updated')]
  )
  environments_error = [c for c in processed_components if c[1].get('env_error')]
  qty_environments_error = len(environments_error)

  summary = '\n\nCOMPONENT SUMMARY\n=================\n'
  summary += f'{qty_components} components processed\n'
  summary += f'- {qty_components_env_changed} had an environment configuration update\n'
  summary += f'-  {qty_components_main_changed} had a main branch update\n\n'
  if components_update_error:
    summary += '\nComponents with update errors:\n'
    for c in components_update_error:
      summary += f'  {c[0]}\n'
  if components_not_found:
    summary += '\nComponents not found / not accessible in Github:\n'
    for c in components_not_found:
      summary += f'- {c[0]}\n'
  if components_app_disabled:
    summary += '\nComponents requiring Github App to be enabled:\n'
    for c in components_app_disabled:
      summary += f'- {c[0]}\n'
  if components_branch_protection_disabled:
    summary += '\nComponents with branch protection disabled:\n'
    for c in components_branch_protection_disabled:
      summary += f'- {c[0]}\n'
  summary += '\n'

  summary += 'ENVIRONMENT SUMMARY\n==================\n'
  summary += f'- {qty_environments_added} environment(s) added\n'
  summary += f'-  {qty_environments_updated} environment(s) updated\n'
  summary += f'-  {qty_environments_error} environment(s) encountered errors\n\n'
  if environments_error:
    summary += '\nEnvironments with errors:\n'
    for c in environments_error:
      summary += f'  {c[0]}\n'

  summary += 'PRODUCT SUMMARY\n===============\n'
  summary += f'{processed_products} products processed\n\n'

  qty_teams = len(processed_teams)
  qty_teams_terraform_managed = len(
    [c for c in processed_teams if c[1].get('terraform_managed')]
  )
  qty_teams_updated = len([c for c in processed_teams if c[1].get('team_updated')])
  qty_teams_added = len([c for c in processed_teams if c[1].get('team_added')])
  teams_failed = [c for c in processed_teams if c[1].get('team_failure')]

  summary += 'TEAM SUMMARY\n===============\n'
  summary += f'{qty_teams} teams processed\n\n'
  summary += f'- {qty_teams_terraform_managed} teams are terraform managed\n'
  summary += f'- {qty_teams_updated} team(s) updated\n'
  summary += f'- {qty_teams_added} team(s) added\n'
  if teams_failed:
    summary += '\nTeams that encountered errors:\n'
    for t in teams_failed:
      summary += f'- {t[0]}\n'

  services.slack.notify(summary)
  services.log.info(summary)


def main():
  logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=log_level
  )
  log = logging.getLogger(__name__)

  #### Create resources ####

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

  slack_params = {
    'token': os.getenv('SLACK_BOT_TOKEN'),
    'notification_channel': os.getenv('SLACK_NOTIFICATION_CHANNEL', ''),
    'alert_channel': os.getenv('SLACK_ALERT_CHANNEL', ''),
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

  services = Services(sc_params, gh_params, am_params, cc_params, slack_params, log)

  # Send some alerts if there are service issues
  if not services.am.json_config_data:
    services.slack.alert('*Github Discovery*: Unable to connect to Alertmanager')

  if not services.cc.test_connection():
    services.slack.alert('*Github Discovery failed*: Unable to connect to CircleCI')
    raise SystemExit()

  if not services.sc.connection_ok:
    services.slack.alert(
      '*Github Discovery failed*: Unable to connect to the Service Catalogue'
    )
    raise SystemExit()

  if not services.gh.org:
    services.slack.alert('*Github Discovery*: Unable to connect to Github')
    raise SystemExit()

  # Since we're running this on a schedule, this is of no further use to us
  # Start health endpoint.
  # health_server = HealthServer()
  # httpHealth = threading.Thread(target=health_server.start, daemon=True)
  # httpHealth.start()

  log.info('Batch processing components')
  processed_components = components.batch_process_sc_components(services, max_threads)

  # Process products
  log.info('Batch processing products...')
  processed_products = products.batch_process_sc_products(services, max_threads)

  # Process Teams
  log.info('Processing teams...')
  processed_teams = github_teams.process_github_teams(services)

  create_summary(services, processed_components, processed_products, processed_teams)


if __name__ == '__main__':
  main()

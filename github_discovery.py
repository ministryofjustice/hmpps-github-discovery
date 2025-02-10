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
- SLACK_NOTIFICATION_CHANNEL: Slack channel for notifications
- SLACK_ALERT_CHANNEL: Slack channel for alerts
- LOG_LEVEL: Log level (default: INFO)

"""

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


# def create_summary(services, processed_components, processed_products, processed_teams):
def create_summary(services, processed_components, processed_products):
  def summarize_processed_items(items, item_type, attributes):
    summary = f'\n\n{item_type.upper()} SUMMARY\n{"=" * (len(item_type) + 8)}\n'
    summary += f'{len(items)} {item_type.lower()}(s) processed\n'
    for attr, desc in attributes.items():
      filtered_items = [item for item in items if item[1].get(attr)]
      summary += f'- {len(filtered_items)} {desc}\n'
      if filtered_items:
        summary += f'{desc.capitalize()}:\n'
        for item in filtered_items:
          summary += f'  {item[0]}\n'
    return summary

  component_attributes = {
    'env_changed': 'had an environment configuration update',
    'main_changed': 'had a main branch update',
    'update_error': 'with update errors',
    'not_found': 'not found / not accessible in Github',
    'app_disabled': 'requiring Github App to be enabled',
    'branch_protection_disabled': 'with branch protection disabled',
    'env_added': 'environment(s) added',
    'env_updated': 'environment(s) updated',
    'env_error': 'environment(s) encountered errors',
  }

  # team_attributes = {
  #   'terraform_managed': 'teams are terraform managed',
  #   'team_updated': 'team(s) updated',
  #   'team_added': 'team(s) added',
  #   'team_failure': 'teams that encountered errors',
  # }

  summary = summarize_processed_items(
    processed_components, 'component', component_attributes
  )
  summary += summarize_processed_items(
    processed_products, 'product', {'': 'products processed'}
  )
  # summary += summarize_processed_items(processed_teams, 'team', team_attributes)

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

  # # Process Teams - carried out in a separate script now
  # log.info('Processing teams...')
  # processed_teams = github_teams.process_github_teams(services)

  # create_summary(services, processed_components, processed_products, processed_teams)
  create_summary(services, processed_components, processed_products)


if __name__ == '__main__':
  main()

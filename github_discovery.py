#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores
the results in the service catalogue

Optional parameters:
-f, --force: Force update of the service catalogue

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
import sys

# Classes for the various parts of the script
# from classes.health import HealthServer
from hmpps import ServiceCatalogue
from hmpps import GithubSession
from hmpps import Slack
from hmpps import AlertmanagerData
from hmpps import CircleCI

# Components
import processes.products as products
import processes.components as components
from hmpps.services.job_log_handling import log_error, log_info, job

# Set maximum number of concurrent threads to run,
# try to avoid secondary github api limits.
max_threads = 10


class Services:
  def __init__(self):
    self.slack = Slack()
    self.sc = ServiceCatalogue()
    self.gh = GithubSession()
    self.am = AlertmanagerData()
    self.cc = CircleCI()


def create_summary(
  services,
  processed_components,
  processed_products,
  duplicate_appinsights_cloud_role,
  force_update=False,
):
  # Summarize the items based on the attributes

  def summarize_processed_components(items, item_type, attributes, force_update=False):
    if force_update:
      summary = f'\n\n{item_type.upper()} SUMMARY\n{"=" * (len(item_type) + 8)}\n'
      summary += f'{len(items)} {item_type.lower()}(s) processed\n'
      for attr, desc in attributes.items():
        filtered_items = [item for item in items if item[1].get(attr)]
        summary += f'- {len(filtered_items)} {desc}\n'
        if filtered_items and 'update' not in desc and 'add' not in desc:
          for item in filtered_items:
            summary += f'  {item[0]}\n'
          summary += '\n'
    else:
      summary = f'{len(items)} {item_type.lower()}(s) processed\n'
      for attr, desc in attributes.items():
        filtered_items = [item for item in items if item[1].get(attr)]
        if filtered_items and 'update' not in desc and 'add' not in desc:
          summary += f'- {len(filtered_items)} {desc}\n'
          for item in filtered_items:
            summary += f'  {item[0]}\n'
          summary += '\n'
    return summary

  def summarize_processed_products(qty, item_type, force_update=False):
    if force_update:
      summary = f'\n\n{item_type.upper()} SUMMARY\n{"=" * (len(item_type) + 8)}\n'
      summary += f'{qty} {item_type.lower()}(s) processed\n'
    else:
      summary = f'{qty} {item_type.lower()}(s) processed\n'
    return summary

  def summarize_duplicate_app_role_with_details(
    duplicate_roles, item_type, force_update=False
  ):
    """
    Summarizes duplicate Application Insights Cloud Role Names with component details.
    """
    summary = ''
    if force_update:
      summary += f'\n\n{item_type.upper()} SUMMARY\n{"=" * (len(item_type) + 8)}\n'

    if len(duplicate_roles) > 0 or force_update:
      summary += (
        f'{len(duplicate_roles)} {item_type.lower()}(s) found with duplicate '
        f'Application Insights Cloud Role Name\n'
      )
      for role_name, components in duplicate_roles.items():
        summary += f'\nCloud Role: {role_name}\n'
        summary += f'{"-" * (len(role_name) + 12)}\n'
        for component in components:
          summary += f'  - Component: {component}\n'

    return summary

  component_attributes = {
    'env_changed': 'had an environment configuration update',
    'main_changed': 'had a main branch update',
    'update_error': 'with update errors',
    'not_found': 'not found / not accessible in Github',
    'app_disabled': 'requiring Github App to be enabled',
    'workflows_disabled': 'with workflows disabled',
    'branch_protection_disabled': 'with branch protection disabled',
    'archived': 'archived (monitoring disabled)',
    'env_added': 'environment(s) added',
    'env_updated': 'environment(s) updated',
    'env_removed': 'environment(s) removed',
    'env_error': 'environment(s) encountered errors',
  }

  # team_attributes = {
  #   'terraform_managed': 'teams are terraform managed',
  #   'team_updated': 'team(s) updated',
  #   'team_added': 'team(s) added',
  #   'team_failure': 'teams that encountered errors',
  # }
  summary = f'Github Discovery completed OK {("full update" if force_update else "")}\n'
  summary += summarize_processed_components(
    processed_components, 'component', component_attributes, force_update
  )
  summary += summarize_processed_products(processed_products, 'product', force_update)
  summary += summarize_duplicate_app_role_with_details(
    duplicate_appinsights_cloud_role, 'component', force_update
  )
  # summary += summarize_processed_items(processed_teams, 'team', team_attributes)
  summary += (
    '\n_(generated by <https://github.com/ministryofjustice/hmpps-github-discovery|'
    'hmpps-github-discovery>)_'
  )
  services.slack.notify(summary)
  log_info(summary)


def main():
  #### Use the -f parameter to force an update regardless of environment /
  # main branch changes
  force_update = False
  if '-f' in sys.argv or '--force' in sys.argv:
    job.name = 'hmpps-github-discovery-full'
    force_update = True
  else:
    job.name = 'hmpps-github-discovery-incremental'

  #### Create resources ####

  services = Services()
  slack = services.slack
  cc = services.cc
  sc = services.sc
  gh = services.gh
  am = services.am

  # Send some alerts if there are service issues
  if not sc.connection_ok:
    slack.alert('*Github Discovery failed*: Unable to connect to the Service Catalogue')
    raise SystemExit()

  if not am.json_config_data:
    slack.alert('*Github Discovery*: Unable to connect to Alertmanager')
    log_error('*Github Discovery*: Unable to connect to Alertmanager')

  if not cc.test_connection():
    slack.alert('*Github Discovery failed*: Unable to connect to CircleCI')
    log_error('*Github Discovery failed*: Unable to connect to CircleCI')
    sc.update_scheduled_job(services, job, 'Failed')
    raise SystemExit()

  if not gh.org:
    slack.alert('*Github Discovery*: Unable to connect to Github')
    log_error('*Github Discovery*: Unable to connect to Github')
    sc.update_scheduled_job(services, job, 'Failed')
    raise SystemExit()

  # Since we're running this on a schedule, this is of no further use to us
  # Start health endpoint.
  # health_server = HealthServer()
  # httpHealth = threading.Thread(target=health_server.start, daemon=True)
  # httpHealth.start()

  log_info('Batch processing components')
  processed_components = components.batch_process_sc_components(
    services, max_threads, force_update=force_update
  )

  # Process products
  log_info('Batch processing products...')
  processed_products = products.batch_process_sc_products(services, max_threads)

  # Report on duplicate Application Insights cloud role names
  duplicate_appinsights_cloud_role = components.find_duplicate_app_cloud_role(
    services, max_threads, force_update=force_update
  )

  create_summary(
    services,
    processed_components,
    processed_products,
    duplicate_appinsights_cloud_role,
    force_update,
  )

  if job.error_messages:
    sc.update_scheduled_job('Errors')
    log_info('Github discovery job completed with errors.')
  else:
    sc.update_scheduled_job('Succeeded')
    log_info('Github discovery job completed successfully.')


if __name__ == '__main__':
  main()

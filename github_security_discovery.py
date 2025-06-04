#!/usr/bin/env python
"""Github security - a separate script that interrogates github API for security info
   about hmpps components and stores the results in the service catalogue

Required environment variables
------------------------------

Github (Credentials for Discovery app that has access to the repositories)
- GITHUB_APP_ID: Github App ID
- GITHUB_APP_INSTALLATION_ID: Github App Installation ID
- GITHUB_APP_PRIVATE_KEY: Github App Private Key

Service Catalogue
- SERVICE_CATALOGUE_API_ENDPOINT: Service Catalogue API endpoint
- SERVICE_CATALOGUE_API_KEY: Service

- SLACK_BOT_TOKEN: Slack Bot Token

Optional environment variables
- SLACK_NOTIFY_CHANNEL: Slack channel for notifications
- SLACK_ALERT_CHANNEL: Slack channel for alerts
- LOG_LEVEL: Log level (default: INFO)
"""

import os

# Classes for the various parts of the script
# from classes.health import HealthServer
from classes.service_catalogue import ServiceCatalogue
from classes.github import GithubSession
from classes.slack import Slack

# Components
import processes.components as components
import processes.scheduled_jobs as sc_scheduled_job
from utilities.job_log_handling import log_debug, log_error, log_info, log_critical, job

# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
max_threads = 10


class Services:
  def __init__(self, sc_params, gh_params, slack_params):
    self.slack = Slack(slack_params)
    self.sc = ServiceCatalogue(sc_params)
    self.gh = GithubSession(gh_params)


# def create_summary(services, processed_components):
def create_summary(services, processed_components):
  # Summarize the items based on the attributes

  def summarize_processed_components(items, item_type, attributes):
    summary = f'\n\n{item_type.upper()} SUMMARY\n{"=" * (len(item_type) + 8)}\n'
    summary += f'{len(items)} {item_type.lower()}(s) processed\n'
    for attr, desc in attributes.items():
      filtered_items = [item for item in items if item[1].get(attr)]
      summary += f'- {len(filtered_items)} {desc}\n'
      if filtered_items and 'update' not in desc and 'add' not in desc:
        for item in filtered_items:
          summary += f'  {item[0]}\n'
        summary += '\n'
    return summary

  component_attributes = {
    'qty_workflows': 'non-core workflows discovered',
  }

  summary = 'Github Security Discovery completed OK\n'
  summary += summarize_processed_components(
    processed_components, 'component', component_attributes
  )

  services.slack.notify(summary)
  log_info(summary)


def main():
  #### Create resources ####
  job.name = 'hmpps-github-discovery-security'

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
    'notify_channel': os.getenv('SLACK_NOTIFY_CHANNEL', ''),
    'alert_channel': os.getenv('SLACK_ALERT_CHANNEL', ''),
  }

  services = Services(sc_params, gh_params, slack_params)
  slack = services.slack
  sc = services.sc
  gh = services.gh

  # Send some alerts if there are service issues
  if not sc.connection_ok:
    slack.alert('*Github Discovery failed*: Unable to connect to the Service Catalogue')
    raise SystemExit()

  if not gh.org:
    slack.alert('*Github Discovery (security)*: Unable to connect to Github')
    log_error('*Github Discovery (security)*: Unable to connect to Github')
    sc_scheduled_job.update(services, 'Failed')
    raise SystemExit()

  # Since we're running this on a schedule, this is of no further use to us
  # Start health endpoint.
  # health_server = HealthServer()
  # httpHealth = threading.Thread(target=health_server.start, daemon=True)
  # httpHealth.start()

  log_info('Batch processing components')
  processed_components = components.batch_process_sc_components(
    services, max_threads, security_only=True
  )

  create_summary(services, processed_components)

  if job.error_messages:
    sc_scheduled_job.update(services, 'Errors')
    log_info('Github security discovery job completed with errors.')
  else:
    sc_scheduled_job.update(services, 'Succeeded')
    log_info('Github security discovery job completed successfully.')


if __name__ == '__main__':
  main()

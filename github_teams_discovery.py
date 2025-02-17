#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue"""

import os
import logging

from processes import github_teams
from classes.github import GithubSession
from classes.service_catalogue import ServiceCatalogue
from classes.slack import Slack


class Services:
  def __init__(self, sc_params, gh_params, slack_params, log):
    self.sc = ServiceCatalogue(sc_params, log)
    self.gh = GithubSession(gh_params, log)
    self.slack = Slack(slack_params, log)
    self.log = log


def summarize_processed_teams(processed_teams):
  item_type = 'Github Teams'
  summary = f'\n\n{item_type.upper()} SUMMARY\n{"=" * (len(item_type) + 8)}\n'
  team_attributes = {
    'terraform_managed': 'teams are terraform managed',
    'team_updated': 'team(s) updated',
    'team_added': 'team(s) added',
    'team_failure': 'teams that encountered errors',
  }
  for attr, desc in team_attributes.items():
    filtered_items = [item for item in processed_teams if item[1].get(attr)]
    summary += f'- {len(filtered_items)} {desc}\n'
    # if filtered_items:
    #   for item in filtered_items:
    #     summary += f'  {item[0]}\n'
    #   summary += '\n'
  return summary


def main():
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

  logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s',
    level=os.getenv('LOG_LEVEL', 'INFO').upper(),
  )
  log = logging.getLogger(__name__)

  services = Services(sc_params, gh_params, slack_params, log)

  log.info('Processing teams...')
  processed_teams = github_teams.process_github_teams(services)
  log.info('Finished processing teams.')

  summary = summarize_processed_teams(processed_teams)
  services.slack.notify(summary)
  services.log.info(summary)


if __name__ == '__main__':
  main()

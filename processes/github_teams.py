#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue"""

import os
import logging
from classes.github import GithubSession
from classes.service_catalogue import ServiceCatalogue

import includes.teams as teams

log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()


class Services:
  def __init__(self, sc_params, gh_params, log):
    self.sc = ServiceCatalogue(sc_params, log)
    self.gh = GithubSession(gh_params, log)
    self.log = log


def process_github_teams(services):
  log = services.log
  sc = services.sc
  gh = services.gh

  processed_teams = []

  # Get the github teams data from SC
  log.info('Retrieving Github teams data ...')
  sc_teams = sc.get_all_records(sc.github_teams)
  # Get the github teams refenered in admin, manintain and write teams from SC
  log.info('Getting Github teams references in components')
  all_repo_ref_gh_teams = sc.find_all_teams_ref_in_sc()

  # Get the data from GH for teams from terraform files
  log.info('Retrieving Github teams terraform data...')
  tf_teamrepo = gh.get_org_repo('hmpps-github-teams')
  tf_teams = teams.fetch_gh_github_teams_data(gh, tf_teamrepo, log)
  tf_team_names = [team['name'] for team in tf_teams]

  combined_team_names = set(tf_team_names).union(all_repo_ref_gh_teams)
  for team_name in combined_team_names:
    team_flags = {}
    gh_team = gh.org.get_team_by_slug(team_name)

    if any(team_name == tf_team for tf_team in tf_team_names):
      terraform_managed = True
      team_flags['terraform_managed'] = True
    else:
      terraform_managed = False
    team_data = {
      'github_team_id': gh_team.id,
      'team_name': team_name,
      'team_description': gh_team.description,
      'terraform_managed': terraform_managed,
      'members': [member.login for member in gh.org.get_team(gh_team.id).get_members()],
    }

    log.debug(f'team_data: {team_data}')
    # Looks wthin Service Catalogue Github Teams for a matching team_name
    log.info(f'Looking for {team_name} in the service catalogue..')
    if sc_team := next(
      (team for team in sc_teams if team['attributes'].get('team_name') == team_name),
      None,
    ):
      # Update the team in SC if anything has changed
      for key in team_data:
        if key in sc_team and team_data[key] != sc_team[key]:
          log.info(f'Updating team {team_name} in the service catalogue')
          if sc.update(sc.github_teams, sc_team.get('id'), team_data):
            team_flags['team_updated'] = True
          else:
            team_flags['team_failure'] = True
          break

    # Create the team in SC
    else:
      log.info(f'Team not found - adding {team_name} to the service catalogue')
      if sc.add(sc.github_teams, team_data):
        team_flags['team_added'] = True
      else:
        team_flags['team_failure'] = True

    processed_teams.append((team_name, team_flags))
  return processed_teams


def main():
  logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=log_level
  )
  log = logging.getLogger(__name__)

  # service catalogue parameters
  sc_params = {
    'sc_api_endpoint': os.getenv('SERVICE_CATALOGUE_API_ENDPOINT'),
    'sc_api_token': os.getenv('SERVICE_CATALOGUE_API_KEY'),
    'sc_filter': os.getenv('SC_FILTER', ''),
  }

  # Github parameters
  gh_params = {
    'app_id': int(os.getenv('GITHUB_APP_ID')),
    'installation_id': int(os.getenv('GITHUB_APP_INSTALLATION_ID')),
    'app_private_key': os.getenv('GITHUB_APP_PRIVATE_KEY'),
  }
  services = Services(sc_params, gh_params, log)

  log.info('Processing teams...')
  processed_teams = process_github_teams(services)
  log.info('Finished processing teams.')

  return processed_teams


if __name__ == '__main__':
  main()

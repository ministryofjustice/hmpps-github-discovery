#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue"""

import os
from classes.github import GithubSession
from classes.service_catalogue import ServiceCatalogue

import includes.teams as teams
import processes.scheduled_jobs as sc_scheduled_job
from utilities.job_log_handling import log_debug, log_error, log_info, log_critical


class Services:
  def __init__(self, sc_params, gh_params):
    self.sc = ServiceCatalogue(sc_params)
    self.gh = GithubSession(gh_params)


def process_github_teams(services):
  sc = services.sc
  gh = services.gh

  processed_teams = []

  # Get the github teams data from SC
  log_info('Retrieving Github teams data ...')
  sc_teams = sc.get_all_records(sc.github_teams)
  # Get the github teams refenered in admin, manintain and write teams from SC
  log_info('Getting Github teams references in components')
  all_repo_ref_gh_teams = sc.find_all_teams_ref_in_sc()
  # Get the data from GH for teams from terraform files
  log_info('Retrieving Github teams terraform data...')
  tf_teamrepo = gh.get_org_repo('hmpps-github-teams')
  tf_teams = teams.fetch_gh_github_teams_data(gh, tf_teamrepo)
  tf_team_names = [team['name'] for team in tf_teams]

  combined_team_names = set(tf_team_names).union(all_repo_ref_gh_teams)
  for team_name in combined_team_names:
    team_flags = {}
    try:
      gh_team = gh.org.get_team_by_slug(team_name)
    except Exception as e:
      log_error(f'Unable to get details for {team_name} in Github - {e}')
      gh_team = None

    if gh_team:
      if any(team_name == tf_team for tf_team in tf_team_names):
        terraform_managed = True
        team_flags['terraform_managed'] = True
      else:
        terraform_managed = False
      team_data = {
        'github_team_id': gh_team.id,
        'team_name': team_name,
        'parent_team_name': gh_team.parent.name if gh_team.parent else None,
        'team_desc': gh_team.description.replace(
          '• This team is managed by Terraform, see https://github.com/ministryofjustice/hmpps-github-teams - DO NOT UPDATE MANUALLY!',
          '',
        )
        if gh_team.description
        else '',
        'terraform_managed': terraform_managed,
        'members': [
          member.login for member in gh.org.get_team(gh_team.id).get_members()
        ],
      }

      log_debug(f'team_data: {team_data}')
      # Looks wthin Service Catalogue Github Teams for a matching team_name
      log_debug(f'Looking for {team_name} in the service catalogue..')
      if sc_team := next(
        (team for team in sc_teams if team['attributes'].get('team_name') == team_name),
        None,
      ):
        sc_team_id = sc_team['id']
        sc_team_attributes = sc_team['attributes']
        # Update the team in SC if anything has changed
        for key in team_data:
          if key in sc_team['attributes'] and team_data[key] != sc_team_attributes[key]:
            log_info(f'Updating team {team_name} in the service catalogue')
            if sc.update(sc.github_teams, sc_team_id, team_data):
              team_flags['team_updated'] = True
            else:
              team_flags['team_failure'] = True
            break

      # Create the team in SC
      else:
        log_info(f'Team not found - adding {team_name} to the service catalogue')
        if sc.add(sc.github_teams, team_data):
          team_flags['team_added'] = True
        else:
          team_flags['team_failure'] = True
    else:
      team_flags['team_failure'] = True
    processed_teams.append((team_name, team_flags))
  return processed_teams

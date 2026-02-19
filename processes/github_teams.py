#!/usr/bin/env python
"""Github discovery - queries the github API for info about hmpps services and stores 
the results in the service catalogue"""

# hmpps
from hmpps import GithubSession, ServiceCatalogue
from hmpps.services.job_log_handling import log_debug, log_error, log_info

# local
import includes.teams as teams


class Services:
  def __init__(self, sc_params, gh_params):
    self.sc = ServiceCatalogue(sc_params)
    self.gh = GithubSession(gh_params)

def remove_team_from_components(sc, team_name):
  log_info(f'Removing team {team_name} from all components in the service catalogue')
  components = sc.get_all_records(sc.components)
  for component in components:
    component_name = component.get("name")
    for team_list_key in ['github_project_teams_admin',
                          'github_project_teams_maintain', 
                          'github_project_teams_write', 
                          'github_project_branch_protection_restricted_teams'
                          ]:
      if team_name in component.get(team_list_key, []):
        component[team_list_key].remove(team_name)
        component_data = { team_list_key: component[team_list_key]}
        log_info(f'Team {team_name} removed from {team_list_key} in {component_name}')
        if sc.update(sc.components, component['documentId'], component_data):
          log_info(f'Team {team_name} removed from component {component["name"]}')
        else:
          log_error(f'Failed to remove team {team_name} from {component_name}')

def find_all_teams_ref_in_sc(sc):
  components = sc.get_all_records(sc.components)
  combined_teams = set()
  for component in components:
    combined_teams.update(component.get('github_project_teams_write', []) or [])
    combined_teams.update(component.get('github_project_teams_admin', []) or [])
    combined_teams.update(component.get('github_project_teams_maintain', []) or [])
  return combined_teams
      
def process_github_teams(services):
  sc = services.sc
  gh = services.gh

  processed_teams = []

  # Get the github teams data from SC
  log_info('Retrieving Github teams data ...')
  sc_teams = sc.get_all_records(sc.github_teams)
  # Get the github teams refenered in admin, manintain and write teams from SC
  log_info('Getting Github teams references in components')
  all_repo_ref_gh_teams = find_all_teams_ref_in_sc(sc)
  # Get the data from GH for teams from terraform files
  log_info('Retrieving Github teams terraform data...')
  tf_teamrepo = gh.get_org_repo('hmpps-github-teams')
  tf_teams = teams.fetch_gh_github_teams_data(gh, tf_teamrepo)
  tf_team_names = [team['name'] for team in tf_teams]

  combined_team_names = set(tf_team_names).union(all_repo_ref_gh_teams)

  for team_name in combined_team_names:
    team_flags = {}
    team_data = {}
    gh_team = None
    try:
      gh_team = gh.org.get_team_by_slug(team_name)
    except Exception as e:
      log_info(f'Unable to get details for {team_name} in Github - {e}')
      if '404' in str(e):
        log_info(f'Team {team_name} not found in GitHub. '
          'Deleting from the service catalogue...')
        team_iterator = (
          team for team in sc_teams if team.get('team_name') == team_name
        )
        sc_team = next(team_iterator, None)
        if sc_team:
          if sc.delete(sc.github_teams, sc_team['documentId']):
            log_info(f'Team {team_name} successfully deleted from service catalogue')
            team_flags['team_deleted'] = True
            remove_team_from_components(sc, team_name)
            team_flags['team_references_removed'] = True
        else:
          remove_team_from_components(sc, team_name)
          team_flags['team_references_removed'] = True

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
          '• This team is managed by Terraform, '
          'see https://github.com/ministryofjustice/hmpps-github-teams - '
          'DO NOT UPDATE MANUALLY!',
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
        (team for team in sc_teams if team.get('team_name') == team_name),
        None,
      ):
        sc_team_id = sc_team['documentId']
        # Update the team in SC if anything has changed
        for key in team_data:
          if key in sc_team and team_data[key] != sc_team[key]:
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

  # Delete teams from SC which are no longer in hmpps-github-teams 
  # if they are marked as terraform_managed in the service catalogue

  log_info('Checking for teams to delete from the service catalogue...')
  for sc_team in sc_teams:
    sc_team_name = sc_team.get('team_name')
    sc_team_terraform_managed = sc_team.get('terraform_managed', False)
    if sc_team_name not in tf_team_names and sc_team_terraform_managed:
      log_info(
        f'Terraform managed {sc_team_name} is in the service catalogue '
        'but not in terraform data anymore - deleting from service catalogue',
      )
      if sc.delete(sc.github_teams, sc_team['documentId']):
        log_info(f'Team {sc_team_name} successfully deleted from the service catalogue')
        processed_teams.append((sc_team_name, {'team_deleted': True}))
      else:
        log_error(f'Failed to delete team {sc_team_name} from the service catalogue')
  return processed_teams

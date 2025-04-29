import re
from utilities.job_log_handling import log_debug, log_error, log_info, log_critical

def fetch_gh_github_teams_data(gh, teamrepo):
  try:
    teams_data = gh.get_file_plain(teamrepo, 'terraform/teams.tf')
  except Exception as e:
    log_error(f'Error fetching teams data from Github - {e}')
    return []

  teams_json_data = extract_tf_teams(teams_data)
  log_info(f'Found {len(teams_json_data)} teams in the terraform file')

  parent_teams_pattern = re.compile(r'parent_teams\s*=\s*\[(.*?)\]', re.DOTALL)
  sub_teams_pattern = re.compile(r'sub_teams\s*=\s*\[(.*?)\]', re.DOTALL)
  team_pattern = re.compile(
    r'\{\s*name\s*=\s*"([^"]+)"\s*parent\s*=\s*"([^"]+)"\s*description\s*=\s*"([^"]+)"\s*\}'
  )

  parent_teams_match = parent_teams_pattern.search(teams_data)
  sub_teams_match = sub_teams_pattern.search(teams_data)

  parent_teams = []
  sub_teams = []

  if parent_teams_match:
    parent_teams_content = parent_teams_match.group(1)
    parent_teams = team_pattern.findall(parent_teams_content)

  if sub_teams_match:
    sub_teams_content = sub_teams_match.group(1)
    sub_teams = team_pattern.findall(sub_teams_content)

  combined_teams = parent_teams + sub_teams
  # Convert to JSON format
  teams_json = [
    {'name': team[0], 'parent': team[1], 'description': team[2]}
    for team in combined_teams
  ]
  log_info(f'Number of teams in terraform file: {len(teams_json)}')
  return teams_json


def extract_tf_teams(terraform_content):
  parent_teams_pattern = re.compile(r'parent_teams\s*=\s*\[(.*?)\]', re.DOTALL)
  sub_teams_pattern = re.compile(r'sub_teams\s*=\s*\[(.*?)\]', re.DOTALL)
  team_pattern = re.compile(
    r'\{\s*name\s*=\s*"([^"]+)"\s*parent\s*=\s*"([^"]+)"\s*description\s*=\s*"([^"]+)"\s*\}'
  )

  parent_teams_match = parent_teams_pattern.search(terraform_content)
  sub_teams_match = sub_teams_pattern.search(terraform_content)

  parent_teams = []
  sub_teams = []

  if parent_teams_match:
    parent_teams_content = parent_teams_match.group(1)
    parent_teams = team_pattern.findall(parent_teams_content)

  if sub_teams_match:
    sub_teams_content = sub_teams_match.group(1)
    sub_teams = team_pattern.findall(sub_teams_content)

  combined_teams = parent_teams + sub_teams
  return combined_teams

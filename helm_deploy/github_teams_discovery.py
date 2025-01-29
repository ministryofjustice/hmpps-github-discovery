#!/usr/bin/env python
'''Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue'''
import os
import http.server
import socketserver
import threading
import logging
import re
from time import sleep
from base64 import b64decode
import base64
from datetime import datetime, timedelta
import requests
from github import Github, Auth
import jwt
from requests.exceptions import SSLError

SC_API_ENDPOINT = os.getenv('SERVICE_CATALOGUE_API_ENDPOINT')
SC_API_TOKEN = os.getenv('SERVICE_CATALOGUE_API_KEY')
GITHUB_APP_ID = int(os.getenv('GITHUB_APP_ID'))
GITHUB_APP_INSTALLATION_ID = int(os.getenv('GITHUB_APP_INSTALLATION_ID'))
GITHUB_APP_PRIVATE_KEY = os.getenv('GITHUB_APP_PRIVATE_KEY')
REFRESH_INTERVAL_HOURS = int(os.getenv('REFRESH_INTERVAL_HOURS', '6'))
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
SC_FILTER = os.getenv('SC_FILTER', '')
SC_ENDPOINT_COMPONENTS = f'{SC_API_ENDPOINT}/v1/components'
SC_PAGE_SIZE = 10
SC_PAGINATION_PAGE_SIZE = f'&pagination[pageSize]={SC_PAGE_SIZE}'
SC_ENDPOINT_TEAMS = f'{SC_API_ENDPOINT}/v1/github-teams'
SC_ENDPOINT_COMPONENTS = f'{SC_API_ENDPOINT}/v1/components'

class HealthHttpRequestHandler(http.server.SimpleHTTPRequestHandler):
  def do_GET(self):
    self.send_response(200)
    self.send_header('Content-type', 'text/plain')
    self.end_headers()
    self.wfile.write(bytes('UP', 'utf8'))
    return
  
def startHttpServer():
  handler_object = HealthHttpRequestHandler
  with socketserver.TCPServer(('', 8080), handler_object) as httpd:
    httpd.serve_forever()

def generate_jwt():
  private_key = b64decode(GITHUB_APP_PRIVATE_KEY).decode('ascii')
  now = datetime.utcnow()
  payload = {
    'iat': now,
    'exp': now + timedelta(minutes=10),
    'iss': GITHUB_APP_ID
  }
  token = jwt.encode(payload, private_key, algorithm='RS256')
  return token

def get_access_token(jwt_token):
  headers = {
    'Authorization': f'Bearer {jwt_token}',
    'Accept': 'application/vnd.github.v3+json'
  }
  response = requests.post(
    f'https://api.github.com/app/installations/{GITHUB_APP_INSTALLATION_ID}/access_tokens',
    headers=headers
  )
  response.raise_for_status()
  return response.json()['token']

def fetch_sc_github_teams_data():
  all_sc_teams_data = []  
  try:
    r = requests.get(SC_ENDPOINT_TEAMS, headers=sc_api_headers, timeout=10)
  except Exception as e:
    log.error(f"Error getting team in the SC: {e}")
    return None

  if r.status_code == 200:
    j_meta = r.json()["meta"]["pagination"]
    log.debug(f"Got result page: {j_meta['page']} from SC")
    all_sc_teams_data.extend(r.json()["data"])
  else:
    raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")
    return None

  # Loop over the remaining pages and collect all data
  num_pages = j_meta['pageCount']
  for p in range(2, num_pages + 1):
    page = f"&pagination[page]={p}"
    r = requests.get(f"{SC_ENDPOINT_TEAMS}{page}", headers=sc_api_headers, timeout=10)
    if r.status_code == 200:
      log.debug(f"Got result page: {p} from SC")
      all_sc_teams_data.extend(r.json()["data"])
    else:
      raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")
      return None
  log.info(f"Number of github team records in SC: {len(all_sc_teams_data)}")
  return all_sc_teams_data

def fetch_sc_components_data():
  all_sc_components_data = []  
  try:
    r = requests.get(SC_ENDPOINT_COMPONENTS, headers=sc_api_headers, timeout=10)
  except Exception as e:
    log.error(f"Error getting components from SC: {e}")
    return None

  if r.status_code == 200:
    j_meta = r.json()["meta"]["pagination"]
    log.debug(f"Got result page: {j_meta['page']} from SC")
    all_sc_components_data.extend(r.json()["data"])
  else:
    raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")
    return None

  # Loop over the remaining pages and collect all data
  num_pages = j_meta['pageCount']
  for p in range(2, num_pages + 1):
    page = f"&pagination[page]={p}"
    r = requests.get(f"{SC_ENDPOINT_TEAMS}{page}", headers=sc_api_headers, timeout=10)
    if r.status_code == 200:
      log.debug(f"Got result page: {p} from SC")
      all_sc_components_data.extend(r.json()["data"])
    else:
      raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")
      return None
  log.info(f"Number of components records in SC: {len(all_sc_components_data)}")
  return all_sc_components_data

def fetch_gh_github_teams_data():
  teams_contents = teamrepo.get_contents('terraform/teams.tf')
  teams_data = base64.b64decode(teams_contents.content).decode('utf-8')
  teams_json_data= extract_teams(teams_data)
  log.info(f'Found {len(teams_json_data)} teams in the terraform file')
  return teams_json_data

def find_github_team(team_name):
    for item in sc_teams_json_data:
        if item['attributes'].get('team_name') == team_name:
            return item
    return None

def extract_teams(terraform_content):
    parent_teams_pattern = re.compile(r'parent_teams\s*=\s*\[(.*?)\]', re.DOTALL)
    sub_teams_pattern = re.compile(r'sub_teams\s*=\s*\[(.*?)\]', re.DOTALL)
    team_pattern = re.compile(r'\{\s*name\s*=\s*"([^"]+)"\s*parent\s*=\s*"([^"]+)"\s*description\s*=\s*"([^"]+)"\s*\}')

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
    # Convert to JSON format
    teams_json = [
        {
            "name": team[0],
            "parent": team[1],
            "description": team[2]
        }
        for team in combined_teams
    ]
    log.info(f'Number of teams in terraform file: {len(teams_json)}')
    return teams_json


def find_all_teams_ref_in_sc(sc_teams_json_data):
  components = fetch_sc_components_data()
  combined_teams = set()
  for component in components:
    attributes = component.get('attributes', {})
    combined_teams.update(attributes.get('github_project_teams_write', []) or [])
    combined_teams.update(attributes.get('github_project_teams_admin', []) or [])
    combined_teams.update(attributes.get('github_project_teams_maintain', []) or [])
  return combined_teams

def process_teams():
  tf_team_names = [team["name"] for team in tf_teams_json_data]
  combined_team_names = set(tf_team_names).union(all_repo_ref_gh_teams)
  for team in combined_team_names:
    insert_github_team(team, tf_team_names)
  return None

def insert_github_team(team_name, tf_team_names):
  try:
    gh_team = org.get_team_by_slug(team_name)
  except Exception as e:
    log.error(f"Error getting team {team_name} from github: {e}")
    return None
  c_team = find_github_team(team_name)
  check_team = c_team.get('attributes', {}) if c_team else {}
  c_team_id = c_team.get('id', None) if c_team else None
  team_id = gh_team.id
  team_description = gh_team.description
  parent_team_name= gh_team.parent.name if gh_team.parent else None
  members = [member.login for member in org.get_team(team_id).get_members()]
  if any(team_name == tf_team for tf_team in tf_team_names):
    terraform_managed =  True
  else:
     terraform_managed =  False
  team_data = {
    'github_team_id': team_id,
    'team_name': team_name,
    'parent_team_name': parent_team_name,
    'team_desc': gh_team.description.replace('• This team is managed by Terraform, see https://github.com/ministryofjustice/hmpps-github-teams - DO NOT UPDATE MANUALLY!', '') if gh_team.description else '',
    'members': members,
    'terraform_managed': terraform_managed,
  }
  if c_team_id:
    # Update the team in SC
    try:
      x = requests.put(
        f'{SC_API_ENDPOINT}/v1/github-teams/{c_team_id}',
          headers=sc_api_headers,
          json={'data': team_data},
          timeout=10,
        )
      log.info(f'Successfully updated team {team_name}: {x.status_code}')
    except requests.exceptions.Timeout as timeout_error:
      log.error(f"Timeout error occurred: {timeout_error}")
    except SSLError as ssl_error:
      log.error(f"SSL error occurred: {ssl_error}")
    except requests.exceptions.RequestException as req_error:
      log.error(f"Request error occurred: {req_error}")
  else:
    # Create the team in SC
    try:
      x = requests.post(
        f'{SC_API_ENDPOINT}/v1/github-teams',
          headers=sc_api_headers,
          json={'data': team_data},
          timeout=10,
        )
      log.info(f'Successfully added team {team_name}: {x.status_code}')
    except requests.exceptions.Timeout as timeout_error:
      log.error(f"Timeout error occurred: {timeout_error}")
    except SSLError as ssl_error:
      log.error(f"SSL error occurred: {ssl_error}")
    except requests.exceptions.RequestException as req_error:
      log.error(f"Request error occurred: {req_error}")
  return None

if __name__ == '__main__':
  
  logging.basicConfig(
    format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=LOG_LEVEL
  )
  log = logging.getLogger(__name__)
  sc_api_headers = {
    'Authorization': f'Bearer {SC_API_TOKEN}',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  }

  # Test connection to Service Catalogue
  try:
    r = requests.head(
      f'{SC_API_ENDPOINT}/_health', headers=sc_api_headers, timeout=10
    )
    log.info(f'Successfully connected to the Service Catalogue. {r.status_code}')
  except Exception as e:
    log.critical('Unable to connect to the Service Catalogue.')
    raise SystemExit(e) from e
  

# Test auth and connection to github
  try:
    jwt_token = generate_jwt()
    access_token = get_access_token(jwt_token) # Token is valid only for 10 mins so we need to re-authenticate every 10 mins
    auth = Auth.Token(access_token) 
    gh = Github(auth=auth, pool_size=50)
    org=gh.get_organization('ministryofjustice')
    rate_limit = gh.get_rate_limit()
    core_rate_limit = rate_limit.core
    log.info(f'Github API: {rate_limit}')
  except Exception as e:
    log.critical('Unable to connect to the github API.')
    raise SystemExit(e) from e
  
  # Start health endpoint.
  httpHealth = threading.Thread(target=startHttpServer, daemon=True)
  httpHealth.start()

  # Get the github teams data from SC
  log.info('Retrieving Github teams data ...')
  sc_teams_json_data = fetch_sc_github_teams_data()
  # Get the github teams refenered in admin, manintain and write teams from SC
  all_repo_ref_gh_teams=find_all_teams_ref_in_sc(sc_teams_json_data)
  # Get the data from GH for the teams
  log.info('Retrieving Github teams data for organisation ...')
  teamrepo = gh.get_repo('ministryofjustice/hmpps-github-teams')
  org_gh_teams = org.get_teams()
    
  # Get the data from GH for teams from terraform files 
  log.info('Retrieving Github teams terraform data...')
  tf_teams_json_data = fetch_gh_github_teams_data()

  log.info('Processing teams...')
  process_teams()
  log.info('Finished processing teams.')
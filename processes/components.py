import logging
import threading
import os
import re
import json
from time import sleep
from datetime import datetime

from classes.service_catalogue import ServiceCatalogue
from classes.github import GithubSession
from classes.circleci import CircleCI
from classes.alertmanager import AlertmanagerData
from classes.slack import Slack

# Standalone functions
import includes.helm as helm
from includes.utils import update_dict, get_dockerfile_data
import includes.environments as environments


log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
max_threads = 10


class Services:
  def __init__(self, sc_params, gh_params, am_params, cc_params, slack_params, log):
    self.sc = ServiceCatalogue(sc_params, log)
    self.gh = GithubSession(gh_params, log)
    self.am = AlertmanagerData(am_params, log)
    self.cc = CircleCI(cc_params, log)
    self.slack = Slack(slack_params, log)
    self.log = log


# Repo functions - teams and branch protection
def get_repo_teams_info(repo, branch_protection, component_flags, log):
  data = {}
  branch_protection_restricted_teams = []
  teams_write = []
  teams_admin = []
  teams_maintain = []

  if not component_flags['app_disabled']:
    if not component_flags['branch_protection_disabled']:
      try:
        branch_protection_teams = branch_protection.get_team_push_restrictions() or []
        for team in branch_protection_teams:
          branch_protection_restricted_teams.append(team.slug)
      except Exception as e:
        log.error(f'Unable to get branch protection {repo.name}: {e}')
        component_flags['app_disabled'] = True

    try:
      teams = repo.get_teams()
      for team in teams:
        team_permissions = team.get_repo_permission(repo)
        if team_permissions.admin:
          teams_admin.append(team.slug)
        elif team_permissions.maintain:
          teams_maintain.append(team.slug)
        elif team_permissions.push:
          teams_write.append(team.slug)

      data['github_project_teams_admin'] = teams_admin
      data['github_project_teams_maintain'] = teams_maintain
      data['github_project_teams_write'] = teams_write
      data['github_project_branch_protection_restricted_teams'] = (
        branch_protection_restricted_teams
      )

      enforce_admins = branch_protection.enforce_admins
      data['github_enforce_admins_enabled'] = enforce_admins

    except Exception as e:
      log.error(f'Unable to get teams/admin information {repo.name}: {e}')
      component_flags['app_disabled'] = True

  return data


def get_repo_properties(repo, default_branch):
  return {
    'language': repo.language,
    'description': f'{"[ARCHIVED] " if repo.archived else ""}{repo.description}',
    'github_project_visibility': repo.visibility,
    'github_repo': repo.name,
    'latest_commit': {
      'sha': default_branch.commit.sha,
      'date_time': default_branch.commit.commit.committer.date.isoformat(),
    },
  }


# This is the main function that processes each component in turn
# 1. Get Github repo data that may change without a commit
# 2. For all components that have a different commit to the SC, get Github repo data that may have changed
#    2a. Then get ancillary stuff like Helm data, alertmanager data, security scan results etc


def branch_independent_components(component, services):
  gh = services.gh
  log = services.log
  component_name = component['attributes']['name']
  github_repo = component['attributes']['github_repo']

  data = {}
  component_flags = {
    'app_disabled': False,
    'branch_protection_disabled': False,
  }

  try:
    repo = gh.get_org_repo(f'{github_repo}')
    default_branch = repo.get_branch(repo.default_branch)
    branch_protection = default_branch.get_protection()
    data.update(get_repo_properties(repo, default_branch))
    data.update(get_repo_teams_info(repo, branch_protection, component_flags, log))
  except Exception as e:
    if 'Branch not protected' in f'{e}':
      component_flags['branch_protection_disabled'] = True
    else:
      log.error(
        f'ERROR accessing ministryofjustice/{repo.name}, check github app has permissions to see it. {e}'
      )
      component_flags['app_disabled'] = True

  try:
    data['github_topics'] = repo.get_topics()
  except Exception as e:
    log.warning(f'Unable to get topics for {repo.name}: {e}')

  if re.search(
    r'([fF]rontend)|(-ui)|(UI)|([uU]ser\s[iI]nterface)',
    f'{component_name} {repo.description}',
  ):
    log.debug("Detected 'frontend|-ui' keyword, setting frontend flag.")
    data['frontend'] = True

  if repo.archived:
    log.debug('Repo is archived')
    component_flags['archived'] = True

  log.debug(
    f'Processed main branch independent components for {component_name}\ndata: {data}'
  )
  return data, component_flags


def branch_changed_components(component, repo, services):
  gh = services.gh
  cc = services.cc
  log = services.log

  # Shortcuts to make it easier to read
  component_name = component['attributes']['name']
  component_project_dir = (
    (component['attributes']['path_to_project'] or component_name)
    if component['attributes']['part_of_monorepo']
    else '.'
  )

  # Reset the data ready for updating
  data = {}  # dictionary to hold all the updated data for the component

  # Information from Helm config
  ################################

  # This will return information about:
  # - Helm environments
  # - Helm chart version
  # - Environment configurations:
  #   - Alertmanager configuration
  #   - Endpoint URLs

  log.debug(f'Getting information for {component_name} from Helm config')
  if helm_data := helm.get_info_from_helm(component, repo, services):
    log.debug(f'Found Helm data for record id {component_name} - {helm_data}')
    data.update(helm_data)

  log.debug(
    f'Finished getting information from helm for {component_name}\ndata: {data}'
  )

  # Information from CircleCI data
  ################################

  if cirlcleci_config := gh.get_file_yaml(repo, '.circleci/config.yml'):
    # Trivy Scan summary - this will be superceded by hmpps-trivy-discovery
    try:
      if trivy_scan_json := cc.get_trivy_scan_json_data(component_name):
        # Add trivy scan result to final data dictionary
        data['trivy_scan_summary'] = trivy_scan_json
        data['trivy_last_completed_scan_date'] = trivy_scan_json.get('CreatedAt')
    except Exception:
      log.debug('Unable to get CircleCI trivy scan results')

    # CircleCI Orb version
    update_dict(data, 'versions', cc.get_circleci_orb_version(cirlcleci_config))

  else:
    # Placeholder for GH Trivy scan business
    log.debug('No CircleCI config found')

  # App insights cloud_RoleName
  if repo.language == 'Kotlin' or repo.language == 'Java':
    app_insights_config = gh.get_file_json(
      repo, f'{component_project_dir}/applicationinsights.json'
    )
    if app_insights_config:
      app_insights_cloud_role_name = app_insights_config['role']['name']
      data['app_insights_cloud_role_name'] = app_insights_cloud_role_name

  if repo.language == 'JavaScript' or repo.language == 'TypeScript':
    package_json = gh.get_file_json(repo, f'{component_project_dir}/package.json')
    if package_json:
      if app_insights_cloud_role_name := package_json.get('name'):
        if re.match(r'^[a-zA-Z0-9-_]+$', app_insights_cloud_role_name):
          data['app_insights_cloud_role_name'] = app_insights_cloud_role_name

  # Gradle config
  build_gradle_config_content = False
  if repo.language == 'Kotlin' or repo.language == 'Java':
    build_gradle_kts_config = gh.get_file_plain(repo, 'build.gradle.kts')
    build_gradle_config_content = build_gradle_kts_config
  # Try alternative location for java projects
  if not build_gradle_config_content:
    build_gradle_java_config = gh.get_file_plain(repo, 'build.gradle')
    build_gradle_config_content = build_gradle_java_config

  if build_gradle_config_content:
    try:
      regex = "id\\(\\'uk.gov.justice.hmpps.gradle-spring-boot\\'\\) version \\'(.*)\\'( apply false)?$"
      hmpps_gradle_spring_boot_version = re.search(
        regex, build_gradle_config_content, re.MULTILINE
      )[1]
      log.debug(
        f'Found hmpps gradle-spring-boot version: {hmpps_gradle_spring_boot_version}'
      )
      update_dict(
        data,
        'versions',
        {'gradle': {'hmpps_gradle_spring_boot': hmpps_gradle_spring_boot_version}},
      )
    except TypeError:
      pass

  # Parse Dockerfile
  if dockerfile_contents := gh.get_file_plain(
    repo, f'{component_project_dir}/Dockerfile'
  ):
    if docker_data := get_dockerfile_data(dockerfile_contents, log):
      update_dict(data, 'versions', {'dockerfile': docker_data})
  # All done with the branch dependent components

  log.debug(
    f'Finished getting other repo information for {component_name}\ndata: {data}'
  )
  return data


###########################################################################################################
# Main component processing function
###########################################################################################################
# This is the core function that will be run in a thread for each component
# It will:
# - Get the latest commit from the SC
# - Run the branch_independent_components function to get the data that can change
#   without a commit/environment change
# - Compare the latest commit with the latest Github commit
# - If they are different, run the branch_changed_components function
# - Update the SC with the new data
# - If there are any errors, set flags to indicate what went wrong
# - Return the flags for the component


def process_sc_component(component, bootstrap_projects, services, force_update=False):
  sc = services.sc
  gh = services.gh
  log = services.log

  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}
  component_flags = {}
  component_name = component['attributes']['name']
  log.info(f'Processing component: {component_name}')

  # Get the latest commit from the SC
  log.debug(f'Getting latest commit from SC for {component_name}')
  if latest_commit := component['attributes'].get('latest_commit'):
    if sha := latest_commit.get('sha'):
      sc_latest_commit = sha
  else:
    sc_latest_commit = None
  log.debug(f'Latest commit in SC for {component_name} is {sc_latest_commit}')
  repo = gh.get_org_repo(f'{component["attributes"]["github_repo"]}')
  if repo:
    gh_latest_commit = repo.get_branch(repo.default_branch).commit.sha
    log.debug(f'Latest commit in Github for {component_name} is {gh_latest_commit}')

    log.info(f'Processing main branch independent components for: {component_name}')
    # Get the fields that aren't updated by a commit to main
    independent_components, component_flags = branch_independent_components(
      component, services
    )

    data.update(independent_components)

    # Logic to check if the branch specific components need to be processed
    current_envs = helm.get_envs_from_helm(component, repo, services)

    log.debug(f'Current environments for {component_name}: {current_envs}')
    # Get the environments from the service catalogue
    sc_envs = component['attributes']['environments']
    log.debug(f'Environments in Service catalogue for {component_name}: {sc_envs}')

    # Check if the environments have changed
    if set(env for env in current_envs) != set(env['name'] for env in sc_envs):
      component_flags['env_changed'] = True
      log.info(f'Environments have changed for {component_name}')
    else:
      component_flags['env_changed'] = False

    # Check if the commit has changed:
    if sc_latest_commit and sc_latest_commit != gh_latest_commit:
      component_flags['main_changed'] = True
      log.info(f'Main commit has changed for {component_name}')
    else:
      component_flags['main_changed'] = False

    ###########################################################################################################
    # Anything after this point is only processed if the repo has been updated (component_flags will have data)
    ###########################################################################################################
    if not (
      component_flags['main_changed'] or component_flags['env_changed'] or force_update
    ):
      log.info(f'No main branch or environment changes for {component_name}')
    else:
      # branch_changed_components function returns a dictionary of further changed fields
      log.info(f'Processing changed components for: {component_name}')
      data.update(branch_changed_components(component, repo, services))

      ###########################################################################################################
      # Processing the environment data - updating the Environments table with information from above
      # Which is basically the environments from the helm charts
      ###########################################################################################################
      component_env_data = []
      # Some environment data may already have been populated from helm
      # It will need to be combined with environments found in bootstrap/Github
      # Then updated in components (once it's been turned into a list)
      if helm_environments := data.get('environments'):
        log.debug(
          f'Helm environment data for {component_name}: {json.dumps(helm_environments, indent=2)}'
        )
      else:
        helm_environments = {}
      component_env_data, env_flags = environments.process_environments(
        component, repo, helm_environments, bootstrap_projects, services
      )
      # only update the environment if there is data in there
      # since Service Catalogue doesn't like an empty list
      if component_env_data:
        data['environments'] = component_env_data
        log.debug(
          f'Final environment data for {component_name}: {json.dumps(data["environments"], indent=2)}'
        )
      # Add environment flags to the component flags, since they're related
      for each_flag in env_flags:
        component_flags[each_flag] = env_flags[each_flag]

    # Update component with all results in data dictionary
    if not sc.update(sc.components, component['id'], data):
      log.error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  else:  # if the repo doesn't exist
    component_flags['not_found'] = True

  return component_flags


###########################################################################################################
# Main batch dispatcher - this is the process that's called by github_discovery
###########################################################################################################
def batch_process_sc_components(services, max_threads, force_update=False):
  log = services.log
  sc = services.sc
  gh = services.gh

  processed_components = []

  # Get projects.json from bootstrap repo for namespaces data
  bootstrap_repo = gh.get_org_repo('hmpps-project-bootstrap')
  log.info(f'Getting projects.json from {bootstrap_repo.name}')
  bootstrap_projects_json = services.gh.get_file_json(bootstrap_repo, 'projects.json')
  # Convert the project lists to a dictionary for easier lookup
  bootstrap_projects = {}
  for p in bootstrap_projects_json:
    bootstrap_projects.update({p['github_repo_name']: p})

  components = sc.get_all_records(sc.components_get)

  log.info(f'Processing batch of {len(components)} components...')

  threads = []
  component_count = 0
  for component in components:
    component_count += 1
    # Wait until the API limit is reset if we are close to the limit
    cur_rate_limit = services.gh.get_rate_limit()
    log.info(
      f'{component_count}/{len(components)} - preparing to process {component["attributes"]["name"]} ({int(component_count / len(components) * 100)}% complete)'
    )
    log.info(
      f'Github API rate limit {cur_rate_limit.remaining} / {cur_rate_limit.limit} remains -  resets at {cur_rate_limit.reset}'
    )
    while cur_rate_limit.remaining < 500:
      time_delta = cur_rate_limit.reset - datetime.now()
      time_to_reset = abs(time_delta.total_seconds())

      log.info(f'Backing off for {time_to_reset} second, to avoid github API limits.')
      sleep(time_to_reset)

    # Mini function to process the component and store the result
    # because the threading needs to target a function
    def process_component_and_store_result(
      component, bootstrap_projects, services, force_update
    ):
      result = process_sc_component(
        component, bootstrap_projects, services, force_update
      )
      processed_components.append((component['attributes']['name'], result))

    # Create a thread for each component
    t_repo = threading.Thread(
      target=process_component_and_store_result,
      args=(component, bootstrap_projects, services, force_update),
      daemon=True,
    )
    threads.append(t_repo)

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (max_threads - 1):
      log.debug(f'Active Threads={threading.active_count()}, Max Threads={max_threads}')
      sleep(10)

    t_repo.start()
    log.info(f'Started thread for component {component["attributes"]["name"]}')

  # wait until all the threads are finished
  for t in threads:
    t.join()

  return processed_components


###########################################################################################################
# In case it's run as a standalone script
###########################################################################################################
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

  circle_ci_params = {
    'url': os.getenv(
      'CIRCLECI_API_ENDPOINT',
      'https://circleci.com/api/v1.1/project/gh/ministryofjustice/',
    ),
    'token': os.getenv('CIRCLECI_TOKEN'),
  }
  am_params = {
    'alertmanager_endpoint': os.getenv(
      'ALERTMANAGER_ENDPOINT',
      'http://monitoring-alerts-service.cloud-platform-monitoring-alerts:8080/alertmanager/status',
    )
  }

  slack_params = {
    'token': os.getenv('SLACK_BOT_TOKEN'),
    'notification_channel': os.getenv('SLACK_NOTIFICATION_CHANNEL', ''),
    'alert_channel': os.getenv('SLACK_ALERT_CHANNEL', ''),
  }

  services = Services(
    sc_params, gh_params, circle_ci_params, am_params, slack_params, log
  )

  log.info('Processing components...')
  processed_components = batch_process_sc_components(services, max_threads)
  log.info(f'Processed components: {processed_components}')


if __name__ == '__main__':
  main()

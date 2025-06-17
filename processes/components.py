import threading
import sys
import re
import json
import importlib

from time import sleep
from datetime import datetime, timezone

from classes.service_catalogue import ServiceCatalogue
from classes.github import GithubSession
from classes.circleci import CircleCI
from classes.alertmanager import AlertmanagerData
from classes.slack import Slack

# Standalone functions
from includes import helm, environments
from includes.utils import update_dict, get_dockerfile_data

import processes.scheduled_jobs as sc_scheduled_job
from utilities.job_log_handling import (
  log_debug,
  log_error,
  log_info,
  log_critical,
  log_warning,
)

max_threads = 10


class Services:
  def __init__(self, sc_params, gh_params, am_params, cc_params, slack_params):
    self.sc = ServiceCatalogue(sc_params)
    self.gh = GithubSession(gh_params)
    self.am = AlertmanagerData(am_params)
    self.cc = CircleCI(cc_params)
    self.slack = Slack(slack_params)


# Read the projects.json from the bootstrap project into a dictionary
#####################################################################
def get_bootstrap_projects(services):
  gh = services.gh
  # Get projects.json from bootstrap repo for namespaces data
  bootstrap_repo = gh.get_org_repo('hmpps-project-bootstrap')
  log_info(f'Getting projects.json from {bootstrap_repo.name}')
  bootstrap_projects_json = services.gh.get_file_json(bootstrap_repo, 'projects.json')
  # Convert the project lists to a dictionary for easier lookup
  bootstrap_projects = {}
  for p in bootstrap_projects_json:
    bootstrap_projects.update({p['github_repo_name']: p})
  return bootstrap_projects


# Github repo functions - teams and branch protection
#####################################################
def get_repo_teams_info(repo, branch_protection):
  data = {}
  branch_protection_restricted_teams = []
  teams_write = []
  teams_admin = []
  teams_maintain = []

  if branch_protection:
    try:
      branch_protection_teams = branch_protection.get_team_push_restrictions() or []
      for team in branch_protection_teams:
        branch_protection_restricted_teams.append(team.slug)
    except Exception as e:
      log_warning(f'Unable to get branch protection teams for {repo.name}: {e}')

    try:
      if enforce_admins := branch_protection.enforce_admins:
        data['github_enforce_admins_enabled'] = enforce_admins
    except Exception as e:
      log_warning(f'Unable to get enforce admins details for {repo.name}: {e}')

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

  except Exception as e:
    log_warning(f'Unable to get teams/admin information {repo.name}: {e}')

  return data


# Github repo functions - basic properties
##########################################
def get_repo_properties(repo, default_branch):
  log_debug('get_repo_properties running')
  return {
    'language': repo.language,
    'description': f'{"[ARCHIVED] " if repo.archived and "ARCHIVED" not in repo.description else ""}{repo.description}',
    'github_project_visibility': repo.visibility,
    'github_repo': repo.name,
    'latest_commit': {
      'sha': default_branch.commit.sha,
      'date_time': default_branch.commit.commit.committer.date.isoformat(),
    },
  }


# Repo default branch properties
def get_repo_default_branch(repo):
  try:
    default_branch = repo.get_branch(repo.default_branch)
  except Exception as e:
    log_warning(
      f'Unable to get branch details for ministryofjustice/{repo.name} - please check github app has permissions to see it. {e}'
    )
    return None
  return default_branch


##################################################################################
# Independent Component Function - runs every time the scan takes place
##################################################################################
def process_independent_component(component, services):
  gh = services.gh
  component_name = component['attributes']['name']
  github_repo = component['attributes']['github_repo']

  data = {}
  component_flags = {
    'app_disabled': False,
    'branch_protection_disabled': None,
  }

  try:
    repo = gh.get_org_repo(f'{github_repo}')
  except Exception as e:
    log_warning(
      f'Unable to get details for ministryofjustice/{repo.name} - please check github app has permissions to see it. {e}'
    )
    component_flags['app_disabled'] = True
    return

  # Default branch attributes
  if default_branch := get_repo_default_branch(repo):
    data.update(get_repo_properties(repo, default_branch))
    try:
      branch_protection = default_branch.get_protection()
    except Exception as e:
      if 'Branch not protected' in f'{e}':
        component_flags['branch_protection_disabled'] = True
      else:
        log_warning(
          f'Unable to get branch protection details for ministryofjustice/{repo.name} - please check github app has permissions to see it. {e}'
        )
        component_flags['app_disabled'] = True
      branch_protection = None

    data.update(get_repo_teams_info(repo, branch_protection))
  # If the app can't read the default branch, it's probably not allowed to see the repo
  else:
    component_flags['app_disabled'] = True

  # Check if workflows are disabled
  log_debug(f'Checking workflows for {component_name}')
  try:
    workflows = repo.get_workflows()
    disabled_workflows = []
    component_flags['workflows_disabled'] = False
    for workflow in workflows:
      if workflow.state != 'active' and workflow.name:
        disabled_workflows.append(workflow.name)
    if disabled_workflows:
      component_flags['workflows_disabled'] = True
      log_info(f'Workflows disabled for {component_name}: {disabled_workflows}')
    else:
      log_debug(f'No disabled workflows in {component_name}')
    data['disabled_workflows'] = disabled_workflows
  except Exception as e:
    log_warning(f'Unable to get workflows for {repo.name}: {e}')

  # Get the repo topics
  try:
    data['github_topics'] = repo.get_topics()
  except Exception as e:
    log_warning(f'Unable to get topics for {repo.name}: {e}')

  # Check to see if the repo is a frontend one (based on the name)
  if re.search(
    r'([fF]rontend)|(-ui)|(UI)|([uU]ser\s[iI]nterface)',
    f'{component_name} {repo.description}',
  ):
    log_debug("Detected 'frontend|-ui' keyword, setting frontend flag.")
    data['frontend'] = True

  # Check to see if the repo is a archived
  if repo.archived:
    log_debug('Repo is archived')
    component_flags['archived'] = True

  log_debug(
    f'Processed main branch independent components for {component_name}\ndata: {data}'
  )
  return data, component_flags


#################################################¢¢¢¢¢############################
# Changed Component Function - only runs if main branch or environment has changed
##################################################################################
def process_changed_component(component, repo, services):
  gh = services.gh
  cc = services.cc

  # Shortcuts to make it easier to read
  component_name = component['attributes']['name']
  component_project_dir = (
    (component['attributes']['path_to_project'] or component_name)
    if component['attributes']['part_of_monorepo']
    else '.'
  )

  # Reset the data ready for updating
  # Include the existing versions
  data = {
    'versions': component.get('attributes', {}).get('versions', {})
  }  # dictionary to hold all the updated data for the component

  # versions may have extant data which has been populated by other processes
  # so populate it now
  data['versions'] = component.get('attributes').get('versions')

  # Information from Helm config
  ################################

  # This will return information about:
  # - Helm environments
  # - Helm chart version
  # - Environment configurations:
  #   - Alertmanager configuration
  #   - Endpoint URLs

  log_debug(f'Getting information for {component_name} from Helm config')
  if helm_data := helm.get_info_from_helm(component, repo, services):
    log_debug(f'Found Helm data for record id {component_name} - {helm_data}')
    data.update(helm_data)

  log_debug(
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
      log_debug('Unable to get CircleCI trivy scan results')

    # CircleCI Orb version
    if circleci_orb_version := cc.get_circleci_orb_version(cirlcleci_config):
      update_dict(data, 'versions', circleci_orb_version)
    else:
      log_debug('No CircleCI orb')

  else:
    # Placeholder for GH Trivy scan business
    log_debug('No CircleCI config found')

  # App insights cloud_RoleName
  #############################

  log_debug('Looking for application insights cloud role name')
  if repo.language == 'Kotlin' or repo.language == 'Java':
    log_debug(
      f'Detected Kotlin/Java - looking in {component_project_dir}/applicationinsights.json'
    )
    app_insights_config = gh.get_file_json(
      repo, f'{component_project_dir}/applicationinsights.json'
    )
    if app_insights_config:
      if app_insights_cloud_role_name := app_insights_config.get('role', {}).get(
        'name'
      ):
        data['app_insights_cloud_role_name'] = app_insights_cloud_role_name
      else:
        log_debug('Role name not found in the expected place (role.name)')
    else:
      log_warning('No applicationinsights.json file found')

  if repo.language == 'JavaScript' or repo.language == 'TypeScript':
    log_debug(
      f'Detected JavaScript/TypeScript - looking in {component_project_dir}/package.json'
    )
    if package_json := gh.get_file_json(repo, f'{component_project_dir}/package.json'):
      if app_insights_cloud_role_name := package_json.get('name'):
        if re.match(r'^[a-zA-Z0-9-_]+$', app_insights_cloud_role_name):
          data['app_insights_cloud_role_name'] = app_insights_cloud_role_name
          log_debug(f'app_insights_cloud_role_name is {app_insights_cloud_role_name}')
        else:
          log_debug('Role name not valid - not setting it')
      else:
        log_debug('Role name not found in the expected place (name)')
    else:
      log_warning('No package.json file found')

  # Gradle config
  ###############

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
      log_debug(
        f'Found hmpps gradle-spring-boot version: {hmpps_gradle_spring_boot_version}'
      )
      update_dict(
        data,
        'versions',
        {'gradle': {'hmpps_gradle_spring_boot': hmpps_gradle_spring_boot_version}},
      )
    except TypeError:
      pass

  # Information from Dockerfile
  #############################
  dockerfile_path = f'{component_project_dir}/Dockerfile'
  if dockerfile_contents := gh.get_file_plain(repo, dockerfile_path):
    if docker_data := get_dockerfile_data(dockerfile_contents):
      # Reprocess the dictionary to include the path name
      docker_versions = {}
      for key, value in docker_data.items():
        docker_versions[key] = {'ref': value, 'path': dockerfile_path}

      update_dict(data, 'versions', {'dockerfile': docker_versions})
  # All done with the branch dependent components

  # End of other component information
  ####################################

  log_debug(
    f'Finished getting other repo information for {component_name}\ndata: {data}'
  )

  return data


###########################################################################################################
# Main component processing function
###########################################################################################################
# This is the core function that will be run in a thread for each component
# It will:
# - Get the latest commit from the SC
# - Run the process_independent_component function to get the data that can change
#   without a commit/environment change
# - Compare the latest commit with the latest Github commit
# - If they are different, run the process_changed_component function
# - Update the SC with the new data
# - If there are any errors, set flags to indicate what went wrong
# - Return the flags for the component


def process_sc_component(component, services, bootstrap_projects, force_update=False):
  sc = services.sc
  gh = services.gh

  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}
  component_flags = {}
  component_name = component['attributes']['name']
  log_info(f'Processing component: {component_name}')

  # Get the latest commit from the SC
  log_debug(f'Getting latest commit from SC for {component_name}')
  if latest_commit := component['attributes'].get('latest_commit'):
    if sha := latest_commit.get('sha'):
      sc_latest_commit = sha
  else:
    sc_latest_commit = None
  log_debug(f'Latest commit in SC for {component_name} is {sc_latest_commit}')
  repo = gh.get_org_repo(f'{component["attributes"]["github_repo"]}')
  if repo:
    gh_latest_commit = repo.get_branch(repo.default_branch).commit.sha
    log_debug(f'Latest commit in Github for {component_name} is {gh_latest_commit}')

    log_info(f'Processing main branch independent components for: {component_name}')
    # Get the fields that aren't updated by a commit to main
    independent_components, component_flags = process_independent_component(
      component, services
    )

    data.update(independent_components)

    component_flags['env_changed'] = environments.check_env_change(
      component, repo, bootstrap_projects, services
    )

    # Check if the commit has changed:
    if sc_latest_commit and sc_latest_commit != gh_latest_commit:
      component_flags['main_changed'] = True
      log_info(f'Main commit has changed for {component_name}')
    else:
      component_flags['main_changed'] = False

    ###########################################################################################################
    # Anything after this point is only processed if the repo has been updated (component_flags will have data)
    ###########################################################################################################
    if not (
      component_flags['main_changed'] or component_flags['env_changed'] or force_update
    ):
      log_info(f'No main branch or environment changes for {component_name}')
    else:
      # process_changed_component function returns a dictionary of further changed fields
      log_info(f'Processing changed components for: {component_name}')
      data.update(process_changed_component(component, repo, services))

      ###########################################################################################################
      # Processing the environment data - updating the Environments table with information from above
      # Which is basically the environments from the helm charts
      ###########################################################################################################
      component_env_data = []
      # Some environment data may already have been populated from helm
      # It will need to be combined with environments found in bootstrap/Github
      # Then updated in components (once it's been turned into a list)
      if helm_environments := data.get('environments'):
        log_debug(
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
        log_debug(
          f'Final environment data for {component_name}: {json.dumps(data["environments"], indent=2)}'
        )
      else:  # if there's no data, remove the environments key
        if data.get('environments'):
          del data['environments']
      # Add environment flags to the component flags, since they're related
      for each_flag in env_flags:
        component_flags[each_flag] = env_flags[each_flag]

    # Update component with all results in data dictionary
    if not sc.update(sc.components, component['id'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  else:  # if the repo doesn't exist
    component_flags['not_found'] = True

  return component_flags


##############################################################################################################
# Main batch dispatcher - this is the process that's called by github_discovery, and github_security_discovery
# By default it runs the function 'process_sc_component' - this can be overridden by a custom function
# (eg. process_sc_security_component)
##############################################################################################################
def batch_process_sc_components(
  services,
  max_threads,
  module='processes.components',
  function='process_sc_component',
  force_update=False,
):
  sc = services.sc

  processed_components = []

  bootstrap_projects = get_bootstrap_projects(services)

  components = sc.get_all_records(sc.components_get)

  log_info(f'Processing batch of {len(components)} components...')

  threads = []
  component_count = 0
  for component in components:
    component_count += 1
    # Wait until the API limit is reset if we are close to the limit
    cur_rate_limit = services.gh.get_rate_limit()
    log_info(
      f'{component_count}/{len(components)} - preparing to process {component["attributes"]["name"]} ({int(component_count / len(components) * 100)}% complete)'
    )
    log_info(
      f'Github API rate limit {cur_rate_limit.remaining} / {cur_rate_limit.limit} remains -  resets at {cur_rate_limit.reset}'
    )
    while cur_rate_limit.remaining < 500:
      cur_rate_limit = services.gh.get_rate_limit()
      time_delta = cur_rate_limit.reset - datetime.now(timezone.utc)
      time_to_reset = time_delta.total_seconds()
      if int(time_to_reset) > 10 and cur_rate_limit.remaining < 500:
        log_info(
          f'Backing off for {time_to_reset + 10} seconds, to avoid github API limits.'
        )
        sleep(
          int(time_to_reset + 10)
        )  # Add a second to avoid irritating fractional settings

    # Mini function to process the component and store the result
    # because the threading needs to target a function
    def process_component_and_store_result(
      component,
      services,
      module,
      function,
      bootstrap_projects,
      force_update,
    ):
      log_debug(f'Function is {function}')
      mod = importlib.import_module(module)
      func = getattr(mod, function)
      if callable(func):
        result = func(
          component,
          services,
          bootstrap_projects=bootstrap_projects,
          force_update=force_update,
        )
        processed_components.append((component['attributes']['name'], result))
      else:
        log_error(f'Unable to call {function}')
        sys.exit(1)

    # Create a thread for each component
    t_repo = threading.Thread(
      target=process_component_and_store_result,
      args=(component, services, module, function, bootstrap_projects, force_update),
      daemon=True,
    )
    threads.append(t_repo)

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (max_threads - 1):
      log_debug(f'Active Threads={threading.active_count()}, Max Threads={max_threads}')
      sleep(10)

    t_repo.start()
    log_info(f'Started thread for component {component["attributes"]["name"]}')

  # wait until all the threads are finished
  for t in threads:
    t.join()

  return processed_components

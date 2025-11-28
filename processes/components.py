import threading
import sys
import re
import json
import importlib

from time import sleep
from datetime import datetime, timezone

# hmpps
from hmpps import (
  ServiceCatalogue,
  GithubSession,
  CircleCI,
  AlertmanagerData,
  Slack,
)
from hmpps import update_dict

from hmpps.services.job_log_handling import (
  log_debug,
  log_error,
  log_info,
  log_warning,
)


# local
from includes import helm, environments, versions

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

  # Branch protection teams
  restricted_teams = []
  if branch_protection:
    try:
      for team in branch_protection.get_team_push_restrictions() or []:
        restricted_teams.append(team.slug)
      data['github_enforce_admins_enabled'] = getattr(
        branch_protection, 'enforce_admins', None
      )
    except Exception as e:
      log_warning(f'Unable to get branch protection info for {repo.name}: {e}')

  # Repo teams and permissions
  try:
    teams_admin, teams_maintain, teams_write = [], [], []
    for team in repo.get_teams():
      perms = team.get_repo_permission(repo)
      if perms.admin:
        teams_admin.append(team.slug)
      elif perms.maintain:
        teams_maintain.append(team.slug)
      elif perms.push:
        teams_write.append(team.slug)
    data.update(
      {
        'github_project_teams_admin': teams_admin,
        'github_project_teams_maintain': teams_maintain,
        'github_project_teams_write': teams_write,
        'github_project_branch_protection_restricted_teams': restricted_teams,
      }
    )
  except Exception as e:
    log_warning(f'Unable to get teams/admin info for {repo.name}: {e}')

  return data


# Github repo functions - basic properties
##########################################
def get_repo_properties(repo, default_branch):
  log_debug('get_repo_properties running')
  description=repo.description or ''
  if repo.archived and "ARCHIVED" not in description:
    description = f"[ARCHIVED] {description}"
  return {
    'language': repo.language,
    'description': description,
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
      f'Unable to get branch details for ministryofjustice/{repo.name} - '
      f'please check github app has permissions to see it. {e}'
    )
    return None
  return default_branch


# Repo disabled workflows
def get_repo_disabled_workflows(repo):
  disabled_workflows = []
  log_debug(f'Checking workflows for {repo.name}')

  try:
    workflows = repo.get_workflows()
    for workflow in workflows:
      if workflow.state not in ['active', 'disabled_manually'] and workflow.name:
        disabled_workflows.append(workflow.name)
    if disabled_workflows:
      log_info(f'Workflows disabled for {repo.name}: {disabled_workflows}')
    else:
      log_debug(f'No disabled workflows in {repo.name}')

  except Exception as e:
    log_warning(f'Unable to get workflows for {repo.name}: {e}')
    return None

  return disabled_workflows


# App insights cloud_RoleName - get the info from the files 
# (dependent on application type)
#######################################################################################
def get_app_insights_cloud_role_name(repo, gh, component_project_dir):
  log_debug('Looking for application insights cloud role name')
  if repo.language == 'Kotlin' or repo.language == 'Java':
    log_debug(
      f'Detected Kotlin/Java - looking in {component_project_dir}/'
      'applicationinsights.json'
    )
    app_insights_config = gh.get_file_json(
      repo, f'{component_project_dir}/applicationinsights.json'
    )
    if app_insights_config:
      if app_insights_cloud_role_name := app_insights_config.get('role', {}).get(
        'name'
      ):
        return app_insights_cloud_role_name
      else:
        log_debug('Role name not found in the expected place (role.name)')
    else:
      log_warning('Kotlin repo - no applicationinsights.json file found for '
                  f'{component_project_dir}')

  if repo.language == 'JavaScript' or repo.language == 'TypeScript':
    log_debug(
      f'Detected JavaScript/TypeScript - '
      f'looking in {component_project_dir}/package.json'
    )
    if package_json := gh.get_file_json(repo, f'{component_project_dir}/package.json'):
      if app_insights_cloud_role_name := package_json.get('name'):
        if re.match(r'^[a-zA-Z0-9-_]+$', app_insights_cloud_role_name):
          return app_insights_cloud_role_name
          log_debug(f'app_insights_cloud_role_name is {app_insights_cloud_role_name}')
        else:
          log_debug('Application Insights role name not valid - not setting it')
      else:
        log_debug(
          'Application Insights role name not found in the expected place (name)'
        )
    else:
      log_warning('Typescript repo - '
                  f'no package.json file found for {component_project_dir}')
  return None


##################################################################################
# Independent Component Function - runs every time the scan takes place
##################################################################################
def process_independent_component(component, repo):
  component_name = component.get('name')

  data = {}
  component_flags = {
    'app_disabled': False,
    'branch_protection_disabled': None,
  }

  # Check to see if the repo is a archived
  if repo.archived:
    log_debug('Repo is archived')
    component_flags['archived'] = True
    data['archived'] = True
    return data, component_flags
  else:
    data['archived'] = False

  # Carry on if the repo isn't archived
  # Default branch attributes
  if default_branch := get_repo_default_branch(repo):
    data.update(get_repo_properties(repo, default_branch))
    try:
      branch_protection = default_branch.get_protection()
    except Exception as e:
      if (
        'Branch not protected' in f'{e}'
        or 'Branch protection has been disabled' in f'{e}'
      ):
        component_flags['branch_protection_disabled'] = True
      else:
        log_warning(
          f'Unable to get branch protection details for ministryofjustice/{repo.name}'
          f' - please check github app has permissions to see it. {e}'
        )
        component_flags['app_disabled'] = True
      branch_protection = None

    data.update(get_repo_teams_info(repo, branch_protection))
  # If the app can't read the default branch, it's probably not allowed to see the repo
  else:
    component_flags['app_disabled'] = True

  # Check if workflows are disabled
  disabled_workflows = get_repo_disabled_workflows(repo)
  data['disabled_workflows'] = disabled_workflows or []
  component_flags['workflows_disabled'] = bool(disabled_workflows)

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

  log_debug(
    f'Processed main branch independent components for {component_name}\ndata: {data}'
  )
  return data, component_flags


#################################################¢¢¢¢¢############################
# Changed Component Function - only runs if main branch or environment has changed
##################################################################################
def process_changed_component(component, repo, services):
  gh = services.gh

  # Shortcuts to make it easier to read
  component_name = component.get('name')
  component_project_dir = (
    (component.get('path_to_project') or component_name)
    if component.get('part_of_monorepo')
    else '.'
  )
  log_debug(f'Component project directory is: {component_project_dir}')

  # Reset the data ready for updating
  data = {}

  # Include the existing versions
  existing_versions = component.get('versions', {})

  # Information from Helm config
  ################################

  # This will return information about:
  # - Helm environments
  # - Helm chart version
  # - Environment configurations:
  #   - Alertmanager configuration
  #   - Endpoint URLs
  # - Product ID if it's valid

  log_debug(f'Getting information for {component_name} from Helm config')
  if helm_data := helm.get_info_from_helm(component, repo, services):
    log_debug(f'Found Helm data for record id {component_name} - {helm_data}')
    # remove previous helm data from existing versions data
    if existing_versions:
      if existing_versions.get('helm_dependencies'):
        existing_versions.pop('helm_dependencies')
      # then update the existing versions into helm data
      update_dict(helm_data, 'versions', existing_versions)
    # ...and update data
    data.update(helm_data)

  log_debug(
    f'Finished getting information from helm for {component_name}\ndata: {data}'
  )

  # App insights cloud_RoleName
  #############################
  if app_insights_cloud_role_name := get_app_insights_cloud_role_name(
    repo, gh, component_project_dir
  ):
    data['app_insights_cloud_role_name'] = app_insights_cloud_role_name
    # only set if app_insights_cloud_role_name is found and 
    # app_insights_alerts_enabled is not False already
    if component.get('app_insights_alerts_enabled') is None: 
      data['app_insights_alerts_enabled'] = True
  else:
    data['app_insights_cloud_role_name'] = None
    data['app_insights_alerts_enabled'] = None

  # Versions information
  versions.get_versions(services, repo, component_project_dir, data)

  # All done with the branch dependent components

  # End of other component information
  ####################################

  log_debug(
    f'Finished getting other repo information for {component_name}\ndata: {data}'
  )

  return data


#######################################################################################
# Main component processing function
#######################################################################################
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

  # Empty data dict gets populated along the way, and finally used 
  # in PUT request to service catalogue
  data = {}
  component_flags = {}
  component_name = component.get('name')
  log_info(f'Processing component: {component_name}')

  # Get the latest commit from the SC
  log_debug(f'Getting latest commit from SC for {component_name}')
  sc_latest_commit = None
  if latest_commit := component.get('latest_commit'):
    if sha := latest_commit.get('sha'):
      sc_latest_commit = sha

  log_debug(f'Latest commit in SC for {component_name} is {sc_latest_commit}')
  repo = gh.get_org_repo(component.get('github_repo', {}))
  if repo:
    gh_latest_commit = repo.get_branch(repo.default_branch).commit.sha
    log_debug(f'Latest commit in Github for {component_name} is {gh_latest_commit}')

    ##############################################################################
    # Process branch / environment independent components (incremental + full)
    ##############################################################################
    log_info(f'Processing main branch independent components for: {component_name}')
    independent_components, component_flags = process_independent_component(
      component, repo
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

    if repo.archived or not (
      component_flags['main_changed'] or component_flags['env_changed'] or force_update
    ):
      log_info(f'No main branch or environment changes for {component_name}')
    else:
      #################################################################################
      # Process component attributes that only change 
      # if main branch / environments have changed (full only)
      #################################################################################
      log_info(f'Processing changed components for: {component_name}')
      data.update(process_changed_component(component, repo, services))

      #################################################################################
      # Processing the environment data - 
      # updating the Environments table with information from above
      # (basically the environments from the helm charts)
      #################################################################################
      # Some environment data may already have been populated from helm
      # It will need to be combined with environments found in bootstrap/Github
      # Then updated in components (once it's been turned into a list)
      if helm_environments := data.get('environments'):
        log_debug(
          f'Helm environment data for {component_name}: '
          f'{json.dumps(helm_environments, indent=2)}'
        )
      else:
        helm_environments = {}
      env_flags = environments.process_environments(
        component, repo, helm_environments, bootstrap_projects, services
      )
      # Add environment flags to the component flags, since they're related
      for each_flag in env_flags:
        component_flags[each_flag] = env_flags[each_flag]
    if 'environments' in data:
      del data['environments']

    # Update component with all results in data dictionary
    if not sc.update(sc.components, component['documentId'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  else:  # if the repo doesn't exist
    component_flags['not_found'] = True

  return component_flags


#######################################################################################
# Main batch dispatcher - this is the process that's called by github_discovery, 
# and github_security_discovery. By default it runs the function 'process_sc_component'
# - this can be overridden by a custom function
# (eg. process_sc_security_component)
#######################################################################################
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
    if component.get('archived'):
      log_info(f'Skipping archived component {component.get("name")}')
      continue
    component_count += 1
    if component.get('archived'):
      log_info(f'Skipping archived component {component.get("name")}')
      continue
    # Wait until the API limit is reset if we are close to the limit
    cur_rate_limit = services.gh.get_rate_limit()
    log_info(
      f'{component_count}/{len(components)} - preparing to process '
      f'{component.get("name")} ({int(component_count/len(components)*100)}% complete)'
    )
    log_info(
      f'Github API rate limit {cur_rate_limit.remaining} / {cur_rate_limit.limit}'
      f'remains -  resets at {cur_rate_limit.reset}'
    )
    while cur_rate_limit.remaining < 500:
      time_delta = cur_rate_limit.reset - datetime.now(timezone.utc)
      time_to_reset = time_delta.total_seconds()
      if int(time_to_reset) > 10:
        log_info(
          f'Backing off for {time_to_reset + 10} seconds, to avoid github API limits.'
        )
        sleep(
          int(time_to_reset + 10)
        )  # Add 10 seconds to avoid irritating fractional settings
        # then re-authenticate so that the cur_rate_limit can refreshed with new session
        log_debug('Reauthenticating')
        services.gh.auth()
      cur_rate_limit = services.gh.get_rate_limit()

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
        processed_components.append((component.get('name'), result))
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
    log_info(f'Started thread for component {component.get("name")}')

  # wait until all the threads are finished
  for t in threads:
    t.join()

  return processed_components

def find_duplicate_app_cloud_role(
    services,
    max_threads,
    module='processes.components',
    function='find_duplicate_app_cloud_role',
    force_update=False,
):
  sc = services.sc

  components = sc.get_all_records(
    'components?filters[archived][$eq]=false'
  )
  log_info(
    f'Processing batch of {len(components)} components '
    'for finding duplicate app insights cloud role names...')

  # Count occurrences of each app_insights_cloud_role_name and group components
  app_insights_cloud_role_counts = {}
  app_insights_cloud_role_components = {}
  for component in components:
    component_name = component.get('name')
    app_insights_cloud_role_name = component.get('app_insights_cloud_role_name', None)
    if app_insights_cloud_role_name:
        app_insights_cloud_role_counts[app_insights_cloud_role_name] = \
            app_insights_cloud_role_counts.get(app_insights_cloud_role_name, 0) + 1
        if app_insights_cloud_role_name not in app_insights_cloud_role_components:
            app_insights_cloud_role_components[app_insights_cloud_role_name] = []
        app_insights_cloud_role_components[app_insights_cloud_role_name].append(
            component_name
        )


  # Filter and log only roles with count > 1
  log_info("Duplicate app insights cloud role names (count > 1):")
  for app_insights_cloud_role_name, count in app_insights_cloud_role_counts.items():
    if count > 1:
      log_info(f"App Insights Cloud Role Name: {app_insights_cloud_role_name}, "
          f"Count: {count}, Components: "
          f"{app_insights_cloud_role_components[app_insights_cloud_role_name]}")

  return {
      app_insights_cloud_role_name: app_insights_cloud_role_components[
          app_insights_cloud_role_name
      ]
      for app_insights_cloud_role_name, count in app_insights_cloud_role_counts.items()
      if count > 1
  }

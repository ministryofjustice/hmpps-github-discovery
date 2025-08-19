# Environment specific functions
# This will prepare data to be updated in the environment table
# as well as returning data to be added to the component table (to be deprecated)
from includes.utils import update_dict, get_existing_env_config
from includes.values import env_mapping
from includes import helm
from utilities.job_log_handling import log_debug, log_error, log_info, log_critical, log_warning


################################################################################################
# get_environments
# This function will get the environments associated with a component
# from the bootstrap projects json file and Github repo environments
################################################################################################
def get_environments(component, repo, bootstrap_projects, services):
  sc = services.sc

  component_name = component.get('name')  # for short
  envs = {}  # using a dictionary to avoid duplicates

  log_debug(f'Getting environments for {component_name} from bootstrap/Github')
  # Check bootstrap first
  if project := bootstrap_projects.get(component.get('github_repo')):
    log_debug(f'Found bootstrap project data for {component_name} - {project}')
    if 'circleci_project_k8s_namespace' in project:
      log_debug(f'Found CircleCI dev namespace for{component_name}')
      update_dict(
        envs,
        'dev',
        {
          'type': 'dev',
          'namespace': project['circleci_project_k8s_namespace'],
          'ns': sc.get_id(
            'namespaces', 'name', project['circleci_project_k8s_namespace']
          ),
        },
      )
    if 'circleci_context_k8s_namespaces' in project:
      for circleci_env in project['circleci_context_k8s_namespaces']:
        log_debug(
          f'Found CircleCI environment {circleci_env["env_name"]} and namespace {circleci_env["namespace"]} for {component_name}'
        )
        if env_type := env_mapping.get(circleci_env.get('env_type')):
          update_dict(
            envs,
            circleci_env['env_name'],
            {
              'type': env_type,
              'namespace': circleci_env['namespace'],
              'ns': sc.get_id('namespaces', 'name', circleci_env['namespace']),
            },
          )

  # Then check Github - these environments take precedence since they're newer
  try:
    repo_envs = repo.get_environments()
  except Exception as e:
    log_error(f'Error getting environments for {component_name}: {e}')

  if repo_envs and repo_envs.totalCount < 10:
    # workaround for a repo that has hundreds of environments
    for repo_env in repo_envs:
      log_debug(
        f'Found environment {repo_env.name} in Github for {component_name} in {repo.name}'
      )
      env_vars = None
      try:
        env_vars = repo_env.get_variables()
      except Exception as e:
        log_debug(f'Unable to get environment variables for {repo_env.name}: {e}')

      # there are some non-standard environments in some of the repos
      # so only process the ones that map to the env_mapping list
      if env_vars:
        if env_type := env_mapping.get(repo_env.name):
          # default settings
          namespace = None
          ns_id = None
          for (
            var
          ) in env_vars:  # We should populate these for all namespaces where possible
            if var.name == 'KUBE_NAMESPACE':
              log_info(f'Found namespace {var.value} for {component_name}')
              namespace = var.value
              ns_id = sc.get_id('namespaces', 'name', var.value)

          update_dict(
            envs,
            repo_env.name,
            {
              'type': env_type,
              'namespace': namespace,
              'ns': ns_id,
            },
          )

  # there's some data that is not populated by Github Discovery, for example
  # the build_image_tag, so loop through the environments and get them from the existing records
  if envs:
    for env in envs:
      log_debug(f'Updating non-discovery fields for environment {env}')
      if build_image_tag := get_existing_env_config(
        component, env, 'build_image_tag', services
      ):
        envs[env]['build_image_tag'] = build_image_tag
        log_debug(f'Added build_image_tag {build_image_tag} to environment {env}')
    log_info(
      f'Environments found in bootstrap/Github for {component_name}: {len(envs)}'
    )

  return envs


###################################################################################################
# process_environments
# This is the main function to process environments based on data from the helm chart
# combined with bootstrap projects json file and Github repo environments
# It returns the environment as a list of dictionaries to be added to the component table
# It also updates the environment table with the environment data, associating it with a component.
###################################################################################################
def process_environments(
  component, repo, helm_environments, bootstrap_projects, services
):
  sc = services.sc

  component_name = component.get('name')
  log_debug(f'Processing environments for {component_name}')
  env_flags = {}

  # This is the final result that will be returned - it's a list of dictionaries
  # since that's how Service Catalogue expects it.
  component_env_data = []

  # Other environment information - get_environments
  # ################################################

  # Populate other component environment data (not from helm)
  # This can come from two places:
  # - the bootstrap projects list (old-style CircleCI)
  # - the repository (new-style Github Actions)
  #
  # Fields within environments that are updated in this section:
  # - namespace
  # - ns_id

  if environment_data := get_environments(
    component, repo, bootstrap_projects, services
  ):
    log_debug(f'Found environments from bootstrap/Github: {environment_data}')
    # The helm environments are used as the primary source of truth for environments
    # since they define the enviroments to which the app can be deployed.
    for helm_env in helm_environments:
      for k, v in environment_data.items():
        if helm_env == k:
          log_debug(f'Found environment {k} in helm environments')
          log_debug(f'Environment data: {v}')
          helm_environments[helm_env].update(v)
          break

  # Time to process the environment table first so we can get the env_id:
  for env in helm_environments:
    # only process the environments that have a valid type
    if not helm_environments[env].get('type') or not helm_environments[env].get(
      'namespace'
    ):
      if not helm_environments[env].get('type'):
        log_info(f'Skipping environment {env} as it has no type')
      if not helm_environments[env].get('namespace'):
        log_info(f'Skipping environment {env} as it has no namespace')
    else:
      # Prepare the environment record with the basic data
      environment_record = helm_environments[env]
      # Link the environment record with the component record
      component_id = sc.get_id('components', 'name', component_name)
      environment_record['component'] = component_id
      # Add the environment name to the environment record
      environment_record['name'] = f'{env}'

      # env_id fix starts here
      env_id = None
      # New logic to look for an environment name corresponding to a component_id
      if env_id := services.sc.get_record(
        services.sc.environments_get,
        f'name][$eq]={env}&filters[component][name',
        f'{component_name}',
      ).get('documentId', ''):
        # print(f'{json.dumps(env, indent=2)}')
        log_info(
          f'Environment ID {env_id} found for environment name {env} associated with {component_name} ({component_id})'
        )
      if env_id:
        # Update the environment in the environment table if anything has changed
        log_info(
          f'Updating environment {env} for {component_name} in the environment table'
        )
        log_debug(f'Environment_record: {environment_record}')
        if sc.update(sc.environments, env_id, environment_record):
          env_flags['env_updated'] = True
        else:
          env_flags['env_error'] = True
      else:
        # Create the environment in the environment table
        log_info(
          f'Environment not found - adding {env} for {component_name} to the environment table'
        )
        log_debug(f'Environment data: {environment_record}')
        if sc.add(sc.environments, environment_record):
          env_flags['env_added'] = True
        else:
          env_flags['env_error'] = True

  # Check if SC has extra environments that are not in the helm chart and delete them from environment table
  current_envs = []
  sc_envs = component.get('envs', {})
  config_envs = get_environments(component, repo, bootstrap_projects, services).keys()
  helm_envs = helm.get_envs_from_helm(component, repo, services)
  for helm_env in helm_envs:
    if helm_env in config_envs:
      current_envs.append(helm_env)
  extra_envs = set(
      env.get('name') for env in sc_envs if isinstance(env, dict)
  ) - set(current_envs)
  extra_envs = [
    env for env in sc_envs
    if isinstance(env, dict) and env.get('name') in extra_envs
  ]
  for env in extra_envs:
    env_id = env.get('documentId')
    env_name = env.get('name')
    log_info(
      f'Environment {env_name} in Service Catalogue is not in the helm chart for {component_name}'
    )
    if sc.delete(sc.environments, env_id):
      log_info(
        f'Environment {env_name} removed from Service Catalogue for {component_name}'
      )
      env_flags['env_removed'] = True
    else:
      log_warning('Failed to remove environment {env_name} from Service Catalogue')
  return env_flags


# Logic to check if the branch specific components need to be processed
def check_env_change(component, repo, bootstrap_projects, services):
  env_changed = False
  component_name = component.get('name')
  current_envs = []
  # Current envs are the combination of helm environments and the bootstrap/Github environments
  config_envs = get_environments(component, repo, bootstrap_projects, services).keys()
  helm_envs = helm.get_envs_from_helm(component, repo, services)

  # get the environments that are common to both the helm and Github/Bootstrap
  for helm_env in helm_envs:
    if helm_env in config_envs:
      current_envs.append(helm_env)

  log_debug(f'Current environments for {component_name}: {current_envs}')
  # Get the environments from the service catalogue
  sc_envs = component.get('envs', {})
  log_debug(f'Environments in Service catalogue for {component_name}: {sc_envs}')

  # Check if the environments have changed
  if set(env for env in current_envs) != set(env.get('name') for env in sc_envs):
    env_changed = True
    log_info(f'Environments have changed for {component_name}')

  return env_changed

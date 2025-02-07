# Environment specific functions
# This will prepare data to be updated in the environment table
# as well as returning data to be added to the component table (to be deprecated)
from includes.utils import update_dict, env_mapping


def get_environments(component, repo, bootstrap_projects, services):
  log = services.log
  sc = services.sc
  gh = services.gh

  component_name = component['attributes']['name']  # for short
  envs = {}  # using a dictionary to avoid duplicates

  log.debug(f'Getting environments for {component_name} from bootstrap/Github')
  # Check bootstrap first
  if project := bootstrap_projects.get(component['attributes']['github_repo']):
    log.debug(f'Found bootstrap project data for {component_name} - {project}')
    if 'circleci_project_k8s_namespace' in project:
      log.debug(f'Found CircleCI dev namespace for{component_name}')
      update_dict(
        envs,
        'dev',
        {
          'type': 'dev',
          'namespace': project['circleci_project_k8s_namespace'],
          'ns_id': sc.get_id(
            'namespaces', 'name', project['circleci_project_k8s_namespace']
          ),
        },
      )
    if 'circleci_context_k8s_namespaces' in project:
      for circleci_env in project['circleci_context_k8s_namespaces']:
        log.debug(
          f'Found CircleCI environment {circleci_env["env_name"]} and namespace {circleci_env["namespace"]} for {component_name}'
        )
        if env_type := env_mapping.get(circleci_env['env_type']):
          update_dict(
            envs,
            circleci_env['env_name'],
            {
              'type': env_type,
              'namespace': circleci_env['namespace'],
              'ns_id': sc.get_id('namespaces', 'name', circleci_env['namespace']),
            },
          )

  # Then check Github - these environments take precedence since they're newer
  repo_envs = repo.get_environments()
  if repo_envs.totalCount < 10:  # workaround for many environments
    for repo_env in repo_envs:
      log.debug(
        f'Found environment {repo_env.name} in Github for {component_name} in {repo.name}'
      )
      env_vars = None
      try:
        env_vars = repo_env.get_variables()
      except Exception as e:
        log.debug(f'Unable to get environment variables for {repo_env.name}: {e}')

      # there are some non-standard environments in some of the repos
      if env_vars:
        if env_type := env_mapping.get(repo_env.name):
          # default settings
          namespace = None
          ns_id = None
          for (
            var
          ) in env_vars:  # We should populate these for all namespaces where possible
            if var.name == 'KUBE_NAMESPACE':
              namespace = var.value
              ns_id = sc.get_id('namespaces', 'name', var.value)

          update_dict(
            envs,
            repo_env.name,
            {
              'type': env_type,
              'namespace': namespace,
              'ns_id': ns_id,
            },
          )
    if envs:
      log.info(
        f'Environments found in bootstrap/Github for {component_name}: {len(envs)}'
      )

  return envs


def process_environments(
  component, repo, helm_environments, bootstrap_projects, services
):
  sc = services.sc
  log = services.log

  component_name = component['attributes']['name']
  log.debug(f'Processing environments for {component_name}')
  env_flags = {}

  # This is the final result that will be returned - it's a dictionary
  # since that's how Service Catalogue expects it.
  component_env_data = []

  # Other environment information
  # #############################

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
    # The helm environments are used as the primary source of truth for environments
    # since they define the enviroments to which the app can be deployed.
    for helm_env in helm_environments:
      for k, v in environment_data.items():
        if helm_env == k:
          log.debug(f'Found environment {k} in helm environments')
          log.debug(f'Environment data: {v}')
          helm_environments[helm_env].update(v)
          break

  # Time to process the environment table first so we can get the env_id:
  for env in helm_environments:
    # only process the environments that have a valid type
    if not helm_environments[env].get('type'):
      log.info(f'Skipping environment {env} as it has no type')
    else:
      # Prepare the environment record with the basic data
      environment_record = helm_environments[env]
      # Link the environment record with the component record
      component_id = sc.get_id('components', 'name', component_name)
      environment_record['component'] = component_id
      # Add the environment name to the environment record
      environment_record['name'] = f'{component_name}-{env}'
      # Check to see if the environment record exists in the environment table
      # With the name formatted as 'component_name-environment_name'
      if env_id := sc.get_id('environments', 'name', f'{component_name}-{env}'):
        # Update the environment in the environment table if anything has changed
        log.info(f'Updating environment {env} in the environment table')
        log.info(f'Environment_record: {environment_record}')
        if sc.update(sc.environments, env_id, environment_record):
          env_flags['env_updated'] = True
        else:
          env_flags['env_error'] = True
      else:
        # Create the environment in the environment table
        log.info(f'Environment not found - adding {env} to the environment table')
        log.info(f'Environment data: {environment_record}')
        if sc.add(sc.environments, environment_record):
          env_flags['env_added'] = True
        else:
          env_flags['env_error'] = True

      # Then prepare the environment for the components table to be returned and added
      helm_environments[env]['name'] = env
      component_env_data.append(helm_environments[env])

  log.debug(f'Component environment data to be added: {component_env_data}')
  return component_env_data, env_flags

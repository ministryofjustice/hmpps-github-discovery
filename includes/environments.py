# Environment specific functions
# This will prepare data to be updated in the environment table
# as well as returning data to be added to the component table (to be deprecated)


def process_environments(component_name, environment_data, services):
  sc = services.sc
  log = services.log

  env_flags = {}
  component_env_data = []

  for env in environment_data:
    # Only process environments where the type is not empty
    if environment_data[env]['type']:
      # Process the environment table first so we can get the env_id:

      # Prepare the environment record with the basic data
      environment_record = environment_data[env]
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
        log.debug(f'Environment_record: {environment_record}')
        if sc.update(sc.environments, env_id, environment_record):
          env_flags['env_updated'] = True
        else:
          env_flags['env_failure'] = True
      else:
        # Create the environment in the environment table
        log.info(f'Environment not found - adding {env} to the environment table')
        log.info(f'Environment data: {environment_record}')
        if sc.add(sc.environments, environment_record):
          env_flags['env_added'] = True
        else:
          env_flags['env_failure'] = True

    # Then prepare the environment for the components table to be returned and added
    environment_data[env]['name'] = env
    component_env_data.append(environment_data[env])
  return component_env_data, env_flags

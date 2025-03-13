import re
import includes.utils as utils
from includes.utils import update_dict, env_mapping, get_existing_env_config


def get_helm_dirs(repo, component, log):
  component_name = component['attributes']['name']

  component_project_dir = (
    component['attributes'].get('path_to_project', component_name)
    if component['attributes'].get('part_of_monorepo')
    else '.'
  )
  helm_dir = (
    component['attributes'].get('path_to_helm_dir')
    or f'{component_project_dir}/helm_deploy'
  )
  log.debug(f'helm_dir for {component_name} is {helm_dir}')

  try:
    helm_deploy_dir = repo.get_contents(
      helm_dir, ref=repo.get_branch(repo.default_branch).commit.sha
    )
  except Exception as e:
    helm_deploy_dir = None
    log.warning(f'Unable to load the helm_deploy folder for {component_name}: {e}')
  return (helm_dir, helm_deploy_dir)


def get_envs_from_helm(component, repo, services):
  log = services.log
  helm_environments = []
  helm_dirs = get_helm_dirs(repo, component, log)
  helm_dir, helm_deploy_dir = helm_dirs
  if helm_deploy_dir:
    for helm_file in helm_deploy_dir:
      if helm_file.name.startswith('values-'):
        env = re.match('values-([a-z0-9-]+)\\.y[a]?ml', helm_file.name)[1]
        helm_environments.append(env)
  return helm_environments


def get_info_from_helm(component, repo, services):
  gh = services.gh
  am = services.am
  log = services.log
  sc = services.sc

  # Shortcuts to make it easier to read
  component_name = component['attributes']['name']

  data = {}

  helm_environments = []
  # environments is returned from helm as a dictionary

  helm_dirs = get_helm_dirs(repo, component, log)
  helm_dir, helm_deploy_dir = helm_dirs
  if helm_deploy_dir:
    # variables used for implementation of findind IP allowlist in helm values files
    allow_list_key = 'allowlist'
    ip_allow_list_data = {}
    ip_allow_list = {}

    # Read in the environments from the helm deployment directory

    for helm_file in helm_deploy_dir:
      if helm_file.name.startswith('values-'):
        env = re.match('values-([a-z0-9-]+)\\.y[a]?ml', helm_file.name)[1]
        helm_environments.append(env)

        # HEAT-223 Start : Read and collate data for IPallowlist from all environment specific values.yaml files.
        ip_allow_list[helm_file] = utils.fetch_yaml_values_for_key(
          gh.get_file_yaml(repo, f'{helm_dir}/{helm_file.name}'),
          allow_list_key,
        )
        if ip_allow_list[helm_file]:
          ip_allow_list_data[helm_file.name] = ip_allow_list[helm_file]
        # HEAT-223 End : Read and collate data for IPallowlist from all environment specific values.yaml files.

    # Helm chart dependencies
    helm_chart = (
      gh.get_file_yaml(repo, f'{helm_dir}/{component_name}/Chart.yaml')
      or gh.get_file_yaml(repo, f'{helm_dir}/Chart.yaml')
      or {}
    )
    if 'dependencies' in helm_chart:
      helm_dep_versions = {}
      for item in helm_chart['dependencies']:
        helm_dep_versions.update({item['name']: item['version']})
      update_dict(data, 'versions', {'helm_dependencies': helm_dep_versions})

    # DEFAULT VALUES SECTION
    # ----------------------
    # Default values for modsecurity and alert_severity_label - clear these out in case theres's nothing set
    mod_security_defaults = {}
    alert_severity_label_default = None
    ip_allow_list_default = {}
    # Get the default values chart filename (including yml versions)
    helm_default_values = (
      gh.get_file_yaml(
        repo, f'{helm_dir}/{component["attributes"]["name"]}/values.yaml'
      )
      or gh.get_file_yaml(
        repo, f'{helm_dir}/{component["attributes"]["name"]}/values.yml'
      )
      or gh.get_file_yaml(repo, f'{helm_dir}/values.yaml')
      or gh.get_file_yaml(repo, f'{helm_dir}/values.yml')
      or {}
    )

    # Get the default values from the helm chart - and only proceed if there is one

    if helm_default_values:
      ip_allow_list_default = utils.fetch_yaml_values_for_key(
        helm_default_values, allow_list_key
      )

      # Try to get the container image
      if container_image := helm_default_values.get('image', {}).get('repository', {}):
        data['container_image'] = container_image
        log.debug(
          f'Container image found in image->repository for {component_name}: {container_image}'
        )
      if 'generic-service' in helm_default_values:
        if 'generic-service' in helm_default_values and (
          container_image := helm_default_values.get('generic-service')
          .get('image')
          .get('repository')
        ):
          data['container_image'] = container_image
          log.debug(
            f'Container image found in generic-service->image->repository for {component_name}: {container_image}'
          )
        # Try to get the productID
        if helm_product_id := helm_default_values.get('generic-service', {}).get(
          'productId', {}
        ):
          data['product'] = sc.get_id('products', 'p_id', helm_product_id)
        # Get modsecurity data defaults, if enabled.
        for mod_security_type in [
          'modsecurity_enabled',
          'modsecurity_audit_enabled',
          'modsecurity_snippet',
        ]:
          mod_security_defaults[mod_security_type] = (
            helm_default_values.get('generic-service', {})
            .get('ingress', {})
            .get(mod_security_type, None)
          )
      if not data.get('container_image'):
        log.info(f'No container image found for {component_name}')

      # If the service catalogue product ID already exists (there is no reason why it shouldn't), use that instead
      # TODO: use the product_id from the repository variables?
      if (
        sc_product_id := component.get('attributes', {})
        .get('product', {})
        .get('data', {})
        .get('id', {})
      ):
        data['product'] = sc_product_id

      alert_severity_label_default = helm_default_values.get(
        'generic-prometheus-alerts', {}
      ).get('alertSeverity', None)

    # Shortcut dictionary to update helm data
    helm_envs = {}

    for env in helm_environments:
      # Environment type first of all:
      update_dict(helm_envs, env, {'type': env_mapping.get(env.lower(), None)})

      # Monitor environment
      if repo.archived:
        # If the repo is archived, then monitoring should be automatically set to False
        update_dict(helm_envs, env, {'monitor': False})

      # Get the values.yaml file for the environment
      values = (
        gh.get_file_yaml(repo, f'{helm_dir}/values-{env}.yaml')
        or gh.get_file_yaml(repo, f'{helm_dir}/values-{env}.yml')
        or None
      )
      log.debug(f'helm values for {component_name} in {env}: {values}')
      if values:
        # generic service->ingress->host(s)
        if 'generic-service' in values:
          if ingress_dict := values['generic-service'].get('ingress'):
            if 'host' in ingress_dict:
              update_dict(helm_envs, env, {'url': f'https://{ingress_dict["host"]}'})
            elif 'hosts' in ingress_dict:
              update_dict(
                helm_envs, env, {'url': f'https://{ingress_dict["hosts"][-1]}'}
              )
        # ingress->host(s)
        elif 'ingress' in values:
          if 'host' in values['ingress']:
            update_dict(helm_envs, env, {'url': f'https://{values["ingress"]["host"]}'})
          elif 'hosts' in values['ingress']:
            update_dict(
              helm_envs, env, {'url': f'https://{values["ingress"]["hosts"][-1]}'}
            )

        # Container image alternative location
        if 'image' in values:
          # image->repository
          if container_image := values.get('image', {}).get('repository', {}):
            data['container_image'] = container_image
          # generic-service->image->repository
          elif 'generic-service' in values and 'image' in values['generic-service']:
            if container_image := values['generic-service']['image']['repository']:
              data['container_image'] = container_image

        # Modsecurity settings
        for mod_security_type in [
          ('modsecurity_enabled', False),
          ('modsecurity_audit_enabled', False),
          ('modsecurity_snippet', None),
        ]:  # default to this
          if 'generic-service' in values and 'ingress' in values['generic-service']:
            if mod_security_env_enabled := values['generic-service']['ingress'].get(
              mod_security_type[0]
            ):
              log.debug(
                f'Updating {mod_security_type[0]} to environment value: {mod_security_env_enabled}'
              )
              update_dict(
                helm_envs,
                env,
                {mod_security_type[0]: mod_security_env_enabled},
              )
            elif mod_security_defaults.get(mod_security_type[0]):
              log.debug(
                f'Updating {mod_security_type[0]} to default value: {mod_security_defaults[mod_security_type[0]]}'
              )
              update_dict(
                helm_envs,
                env,
                {mod_security_type[0]: mod_security_defaults[mod_security_type[0]]},
              )
            else:  # default either to false or None
              update_dict(helm_envs, env, {mod_security_type[0]: mod_security_type[1]})
        if am.isDataAvailable():
          # Update Alert severity label and slack channel
          if generic_prometheus_alerts := values.get('generic-prometheus-alerts'):
            if 'alertSeverity' in generic_prometheus_alerts:
              alert_severity_label = generic_prometheus_alerts['alertSeverity']
              log.debug(f'generic-prometheus alerts found in values: {generic_prometheus_alerts}')
              log.debug(f'Updating {env} alert_severity_label to {alert_severity_label}')

          if alert_severity_label_default and not alert_severity_label:
            log.info(f'Alert severity label not found for {component_name} in {env} - setting to default')
            alert_severity_label = alert_severity_label_default
          else:
            alert_severity_label = None
            log.info(f'Alert severity label not found for {component_name} in values.yaml & values-{env}.yaml')
          
          if alert_severity_label:
            if am.find_channel_by_severity_label(alert_severity_label):
              alerts_slack_channel = am.find_channel_by_severity_label(alert_severity_label)
              log.debug(f'Updating {component_name} {env} alerts_slack_channel to {alerts_slack_channel}')
            else:
              alerts_slack_channel = None
              log.warning(f'Alerts slack channel not found for {component_name} {alert_severity_label} for {env}')
          alertmanager_config = {
            'alert_severity_label': alert_severity_label,
            'alerts_slack_channel': alerts_slack_channel,
          }
          log.debug(f'Alertmanager config for {env} is now: {alertmanager_config}')
          # Update the helm environment data with the outcome of this check
          update_dict(helm_envs, env, alertmanager_config)

        # Health paths using the host name:
        health_path = None
        info_path = None
        if env_host := helm_envs[env].get('url'):
          env_url = f'{env_host}'
          health_path = '/health'
          info_path = '/info'
          # Hack for hmpps-auth non standard endpoints
          if 'sign-in' in env_url:
            health_path = '/auth/health'
            info_path = '/auth/info'
          if utils.test_endpoint(env_url, health_path, log):
            update_dict(helm_envs, env, {'health_path': health_path})
          if utils.test_endpoint(env_url, info_path, log):
            update_dict(helm_envs, env, {'info_path': info_path})
          # Test for API docs - and if found also test for SAR endpoint.
          if utils.test_swagger_docs(env_url, log):
            update_dict(helm_envs, env, {'swagger_docs': '/swagger-ui.html'})
            data['api'] = True
            data['frontend'] = False
            if utils.test_subject_access_request_endpoint(env_url, log):
              update_dict(
                helm_envs,
                env,
                {'include_in_subject_access_requests': True},
              )
            else:
              update_dict(
                helm_envs,
                env,
                {'include_in_subject_access_requests': False},
              )
        # Modification to set monitoring to False if no health path is found
        if not health_path:
          update_dict(helm_envs, env, {'monitor': False})

        if ip_allow_list_env := ip_allow_list_data.get(f'values-{env}.yaml'):
          values_filename = f'values-{env}.yaml'
          allow_list_values = {
            f'{values_filename}': ip_allow_list_env,
            'values.yaml': ip_allow_list_default,
          }
        else:
          allow_list_values = {
            f'values-{env}.yaml': {},
            'values.yaml': ip_allow_list_default,
          }

        update_dict(
          helm_envs,
          env,
          {
            'ip_allow_list': allow_list_values,
            'ip_allow_list_enabled': utils.is_ipallowList_enabled(allow_list_values),
          },
        )

    # Need to add the helm data to the main data list of environments
    if helm_envs:
      update_dict(data, 'environments', helm_envs)
    # End of helm environment checks

  log.debug(f'Helm data for {component_name}: {data}')
  return data

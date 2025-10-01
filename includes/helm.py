import re

# hmpps
from hmpps import update_dict, fetch_yaml_values_for_key
from hmpps.services.job_log_handling import (
  log_debug,
  log_info,
  log_warning,
)

# Locals
from includes.utils import (
  remove_version,
  test_endpoint,
  test_swagger_docs,
  test_subject_access_request_endpoint,
  is_ipallowList_enabled,
)
from includes.values import env_mapping


def get_helm_dirs(repo, component):
  component_name = component.get('name')

  component_project_dir = (
    component.get('path_to_project', component_name)
    if component.get('part_of_monorepo')
    else '.'
  )
  log_debug(f'component_project_dir: {component_project_dir}')
  helm_dir = component.get('path_to_helm_dir') or f'{component_project_dir}/helm_deploy'
  log_debug(f'helm_dir for {component_name} is {helm_dir}')

  try:
    helm_deploy_dir = repo.get_contents(
      helm_dir, ref=repo.get_branch(repo.default_branch).commit.sha
    )
  except Exception as e:
    helm_deploy_dir = None
    log_warning(f'Unable to load the helm_deploy folder for {component_name}: {e}')
  return (helm_dir, helm_deploy_dir)


def get_envs_from_helm(component, repo, services):
  helm_environments = []
  helm_dirs = get_helm_dirs(repo, component)
  helm_dir, helm_deploy_dir = helm_dirs
  if helm_deploy_dir:
    for helm_file in helm_deploy_dir:
      if helm_file.name.startswith('values-'):
        if envs := re.match('values-([a-z0-9-]+)\\.y[a]?ml', helm_file.name):
          helm_environments.append(envs[1])
  return helm_environments


def get_info_from_helm(component, repo, services):
  gh = services.gh
  am = services.am
  sc = services.sc

  # Shortcuts to make it easier to read
  component_name = component.get('name')

  data = {}

  helm_environments = []
  # environments is returned from helm as a dictionary

  helm_dirs = get_helm_dirs(repo, component)
  helm_dir, helm_deploy_dir = helm_dirs
  if helm_deploy_dir:
    # variables used for implementation of findind IP allowlist in helm values files
    allow_list_key = 'allowlist'
    ip_allow_list_data = {}
    ip_allow_list = {}

    # Read in the environments from the helm deployment directory

    for helm_file in helm_deploy_dir:
      if helm_file.name.startswith('values-'):
        if envs := re.match('values-([a-z0-9-]+)\\.y[a]?ml', helm_file.name):
          helm_environments.append(envs[1])

        # HEAT-223 Start : Read and collate data for IPallowlist from all environment specific values.yaml files.
        ip_allow_list[helm_file] = fetch_yaml_values_for_key(
          gh.get_file_yaml(repo, f'{helm_dir}/{helm_file.name}'),
          allow_list_key,
        )
        if ip_allow_list[helm_file]:
          ip_allow_list_data[helm_file.name] = ip_allow_list[helm_file]
        # HEAT-223 End : Read and collate data for IPallowlist from all environment specific values.yaml files.

    # Helm chart dependencies
    helm_file_paths = [
      f'{helm_dir}/{component_name}/Chart.yaml',
      f'{helm_dir}/Chart.yaml',
    ]

    helm_dep_versions = {}

    for path in helm_file_paths:
      if (helm_chart := gh.get_file_yaml(repo, path)) and 'dependencies' in helm_chart:
        helm_dep_versions = {
          item['name']: {'ref': item['version'], 'path': path}
          for item in helm_chart['dependencies']
        }
        break

    if helm_dep_versions:
      update_dict(data, 'versions', {'helm_dependencies': helm_dep_versions})
    else:
      remove_version(data, 'helm_dependencies')

    # DEFAULT VALUES SECTION
    # ----------------------
    # Default values for modsecurity and alert_severity_label - clear these out in case theres's nothing set
    mod_security_defaults = {}
    alert_severity_label_default = None
    ip_allow_list_default = {}
    # Get the default values chart filename (including yml versions)
    helm_default_values = (
      gh.get_file_yaml(repo, f'{helm_dir}/{component.get("name")}/values.yaml')
      or gh.get_file_yaml(repo, f'{helm_dir}/{component.get("name")}/values.yml')
      or gh.get_file_yaml(repo, f'{helm_dir}/values.yaml')
      or gh.get_file_yaml(repo, f'{helm_dir}/values.yml')
      or {}
    )
    log_debug(f'helm_default_values: {helm_default_values}')

    # Get the default values from the helm chart - and only proceed if there is one

    if helm_default_values:
      ip_allow_list_default = fetch_yaml_values_for_key(
        helm_default_values, allow_list_key
      )

      # Try to get the container image
      if container_image := helm_default_values.get('image', {}).get('repository', {}):
        data['container_image'] = container_image
        log_debug(
          f'Container image found in image->repository for {component_name}: {container_image}'
        )
      if 'generic-service' in helm_default_values:
        log_debug(f'generic-service found for {component_name}: {container_image}')
        if 'generic-service' in helm_default_values and (
          container_image := helm_default_values.get('generic-service', {})
          .get('image', {})
          .get('repository')
        ):
          data['container_image'] = container_image
          log_debug(
            f'Container image found in generic-service->image->repository for {component_name}: {container_image}'
          )

        # Try to get the productID from helm values.yaml
        if helm_product_id := helm_default_values.get('generic-service', {}).get(
          'productId', {}
        ):
          if sc_product_id := sc.get_id('products', 'p_id', helm_product_id):
            data['product'] = sc_product_id

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
        log_info(f'No container image found for {component_name}')

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
      log_debug(f'helm values for {component_name} in {env}: {values}')
      if values:
        # generic service->ingress->host(s)
        if 'generic-service' in values:
          if ingress_dict := values['generic-service'].get('ingress'):
            if 'host' in ingress_dict:
              update_dict(helm_envs, env, {'url': f'https://{ingress_dict["host"]}'})
            elif 'hosts' in ingress_dict:
              last_host_record = ingress_dict.get('hosts')[-1]
              log_debug(
                f'hosts found - last record is {last_host_record} - which is of type {type(last_host_record)}'
              )
              host = (
                last_host_record.get('host', '')
                if isinstance(last_host_record, dict)
                else last_host_record
              )
              log_debug(f'host is: {host}')
              update_dict(
                helm_envs,
                env,
                {'url': f'https://{host}'},
              )
        # ingress->host(s)
        elif 'ingress' in values:
          ingress_dict = values.get('ingress')
          if host := ingress_dict.get('host'):
            update_dict(helm_envs, env, {'url': f'https://{host}'})
          elif 'hosts' in ingress_dict:
            last_host_record = ingress_dict.get('hosts')[-1]
            log_debug(
              f'hosts found - last record is {last_host_record} - which is of type {type(last_host_record)}'
            )
            host = (
              last_host_record.get('host', '')
              if isinstance(last_host_record, dict)
              else last_host_record
            )
            log_debug(f'host is: {host}')
            update_dict(
              helm_envs,
              env,
              {'url': f'https://{host}'},
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
              log_debug(
                f'Updating {mod_security_type[0]} to environment value: {mod_security_env_enabled}'
              )
              update_dict(
                helm_envs,
                env,
                {mod_security_type[0]: mod_security_env_enabled},
              )
            elif mod_security_defaults.get(mod_security_type[0]):
              log_debug(
                f'Updating {mod_security_type[0]} to default value: {mod_security_defaults[mod_security_type[0]]}'
              )
              update_dict(
                helm_envs,
                env,
                {mod_security_type[0]: mod_security_defaults[mod_security_type[0]]},
              )
            else:  # default either to false or None
              update_dict(helm_envs, env, {mod_security_type[0]: mod_security_type[1]})

        alert_severity_label = None
        alerts_slack_channel = None
        if am.isDataAvailable():
          # Update Alert severity label and slack channel
          if generic_prometheus_alerts := values.get('generic-prometheus-alerts'):
            alert_severity_label = generic_prometheus_alerts.get('alertSeverity')
            if alert_severity_label:
              log_debug(
                f'generic-prometheus alerts found in values: {generic_prometheus_alerts}'
              )
              log_debug(
                f'Updating {env} alert_severity_label to {alert_severity_label}'
              )

          if not alert_severity_label and alert_severity_label_default:
            log_info(
              f'Alert severity label not found for {component_name} in {env} - setting to default'
            )
            alert_severity_label = alert_severity_label_default
          else:
            log_info(
              f'Alert severity label not found for {component_name} in values.yaml & values-{env}.yaml'
            )

          if alert_severity_label:
            alerts_slack_channel = am.find_channel_by_severity_label(
              alert_severity_label
            )
            if alerts_slack_channel:
              log_debug(
                f'Updating {component_name} {env} alerts_slack_channel to {alerts_slack_channel}'
              )
            else:
              log_warning(
                f'Alerts slack channel not found for {component_name} {alert_severity_label} for {env}'
              )

          alertmanager_config = {
            'alert_severity_label': alert_severity_label,
            'alerts_slack_channel': alerts_slack_channel,
          }
          log_debug(f'Alertmanager config for {env} is now: {alertmanager_config}')
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
          if test_endpoint(env_url, health_path):
            update_dict(helm_envs, env, {'health_path': health_path})
          if test_endpoint(env_url, info_path):
            update_dict(helm_envs, env, {'info_path': info_path})
          # Test for API docs - and if found also test for SAR endpoint.
          if test_swagger_docs(env_url):
            update_dict(helm_envs, env, {'swagger_docs': '/swagger-ui.html'})
            data['api'] = True
            data['frontend'] = False
            if test_subject_access_request_endpoint(env_url):
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
            'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values),
          },
        )

    # Need to add the helm data to the main data list of environments
    if helm_envs:
      update_dict(data, 'environments', helm_envs)
    # End of helm environment checks

  log_debug(f'Helm data for {component_name}: {data}')
  return data

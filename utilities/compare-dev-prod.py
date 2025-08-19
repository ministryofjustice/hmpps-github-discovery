# Classes for the various parts of the script
from classes.service_catalogue import ServiceCatalogue
import os
from utilities.job_log_handling import log_debug, log_info, log_error, log_critical

def compare_attributes(prod_attributes, dev_attributes):
  differences = []

  # Get the union of keys from both dictionaries
  all_keys = set(prod_attributes.keys()).union(set(dev_attributes.keys()))

  for key in all_keys:
    prod_value = prod_attributes.get(key)
    dev_value = dev_attributes.get(key)

    if isinstance(prod_value, dict):
      if prod_value.get('documentId'):
        prod_value.pop('documentId')
    if isinstance(dev_value, dict):
      if dev_value.get('documentId'):
        dev_value.pop('documentId')

    ignored_keys = {
      'product',
      'updatedAt',
      'veracode_results_summary',
      'trivy_scan_summary',
    }
    if prod_value != dev_value and key not in ignored_keys:
      differences.append({'key': key, 'prod_value': prod_value, 'dev_value': dev_value})

  return differences


def main():

  # service catalogue parameters
  sc_dev_params = {
    'url': os.getenv('SERVICE_CATALOGUE_DEV_API_ENDPOINT'),
    'key': os.getenv('SERVICE_CATALOGUE_DEV_API_KEY'),
    'filter': os.getenv('SC_FILTER', ''),
  }

  sc_prod_params = {
    'url': os.getenv('SERVICE_CATALOGUE_PROD_API_ENDPOINT'),
    'key': os.getenv('SERVICE_CATALOGUE_PROD_API_KEY'),
    'filter': os.getenv('SC_FILTER', ''),
  }

  sc_prod = ServiceCatalogue(sc_prod_params)
  sc_dev = ServiceCatalogue(sc_dev_params)

  prod_data = sc_prod.get_all_records(sc_prod.components_get)
  dev_data = sc_dev.get_all_records(sc_dev.components_get)

  for component in prod_data:
    dev_attributes = [
      x['attributes']
      for x in dev_data
      if x.get('name') == component.get('name')
    ][0]
    log_info(f'{prod_attributes["name"]}')
    log_info('=======================')
    differences = compare_attributes(prod_attributes, dev_attributes)
    for diff in differences:
      if diff['key'] == 'environments':
        prod_env_names = {env['name'] for env in diff['prod_value']}
        dev_env_names = {env['name'] for env in diff['dev_value']}
        all_env_names = prod_env_names.union(dev_env_names)

        for env_name in all_env_names:
          prod_env = next(
            (env for env in diff['prod_value'] if env['name'] == env_name), None
          )
          dev_env = next(
            (env for env in diff['dev_value'] if env['name'] == env_name), None
          )
          for key in ['build_image_tag', 'id']:
            if prod_env:
              prod_env.pop(key, None)
            if dev_env:
              dev_env.pop(key, None)

          # Hack for different IP allowlist types
          if prod_env and dev_env:
            if not prod_env.get('ip_allow_list'):
              prod_env['ip_allow_list'] = dev_env['ip_allow_list']
            if not prod_env.get('ip_allow_list_enabled') and not dev_env.get(
              'ip_allow_list_enabled'
            ):
              prod_env['ip_allow_list_enabled'] = dev_env['ip_allow_list_enabled']

          if prod_env != dev_env:
            log_info(f'    Environment {env_name}:')
            log_info(f'      PROD: {prod_env}')
            log_info(f'      DEV: {dev_env}')
      else:
        log_info(
          f'  {diff["key"]}: PROD: {diff["prod_value"]} DEV: {diff["dev_value"]}'
        )
      log_info('\n')


if __name__ == '__main__':
  main()

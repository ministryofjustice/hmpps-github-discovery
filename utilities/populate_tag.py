# Classes for the various parts of the script
from classes.service_catalogue import ServiceCatalogue
import os
import json
from utilities.job_log_handling import log_debug, log_info

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

  prod_components = sc_prod.get_all_records(sc_prod.components_get)
  dev_components = sc_dev.get_all_records(sc_dev.components_get)
  dev_environments = sc_dev.get_all_records(sc_dev.environments)

  for component in prod_components:
    log_info(f'Getting environment data for {component.get("attributes").get("name")}')
    prod_attributes = component['attributes']
    if environments := prod_attributes.get('environments'):
      for env in environments:
        if build_image_tag := env.get('build_image_tag'):
          log_info(
            f'Copying build image tag {build_image_tag} from prod to dev for {component.get("attributes").get("name")}'
          )
          dev_component = next(
            (
              c
              for c in dev_components
              if c['attributes']['name'] == component['attributes']['name']
            ),
            None,
          )
          if dev_component:
            dev_attributes = dev_component.get('attributes')
            # Do the components first
            if dev_environments := dev_attributes.get('environments'):
              for dev_env in dev_environments:
                if dev_env.get('name') == env.get('name'):
                  dev_env['build_image_tag'] = build_image_tag
                  log_info(f'Updated build image tag for {dev_env.get("name")}')
              log_debug(
                f'component environment data is now: {json.dumps(dev_environments, indent=2)}'
              )
              log_info('updating dev component')
              sc_dev.update(
                sc_dev.environments,
                dev_component['id'],
                {'environments': dev_environments},
              )
            # Then do the environment tables
            if dev_env_links := dev_attributes.get('envs').get('data'):
              for dev_env in dev_env_links:
                if dev_env_data := sc_dev.get_record(
                  sc_dev.environments, 'id', dev_env['id']
                ):
                  dev_env_data['build_image_tag'] = build_image_tag
                  log_debug(
                    f'envs environment data for {dev_env_data.get("attributes").get("name")} is now: {json.dumps(dev_env_data, indent=2)}'
                  )
                  log_info('updating dev env')
                  sc_dev.update(
                    sc_dev.environments,
                    dev_env_data['id'],
                    {'build_image_tag': build_image_tag},
                  )
        log_info('\n')


if __name__ == '__main__':
  main()

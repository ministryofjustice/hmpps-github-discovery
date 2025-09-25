import os
import json

# hmpps
from hmpps import ServiceCatalogue
from hmpps.services.job_log_handling import log_debug, log_info


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
    log_info(f'Getting environment data for {component.get("name")}')
    if environments := component.get('environments'):
      for env in environments:
        if build_image_tag := env.get('build_image_tag'):
          log_info(
            f'Copying build image tag {build_image_tag} from prod to dev for {component.get("name")}'
          )
          dev_component = next(
            (c for c in dev_components if c.get('name') == component.get('name')),
            None,
          )
          if dev_component:
            # Do the components first
            if dev_environments := dev_component.get('environments'):
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
                dev_component['documentId'],
                {'environments': dev_environments},
              )
            # Then do the environment tables
            if dev_env_links := dev_component.get('envs'):
              for dev_env in dev_env_links:
                if dev_env_data := sc_dev.get_record(
                  sc_dev.environments, 'documentId', dev_env['documentId']
                ):
                  dev_env_data['build_image_tag'] = build_image_tag
                  log_debug(
                    f'envs environment data for {dev_env_data.get("name")} is now: {json.dumps(dev_env_data, indent=2)}'
                  )
                  log_info('updating dev env')
                  sc_dev.update(
                    sc_dev.environments,
                    dev_env_data['documentId'],
                    {'build_image_tag': build_image_tag},
                  )
        log_info('\n')


if __name__ == '__main__':
  main()

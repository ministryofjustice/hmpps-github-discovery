import os
import json
from classes.service_catalogue import ServiceCatalogue

sc_params = {
  'url': os.getenv('SERVICE_CATALOGUE_API_ENDPOINT'),
  'key': os.getenv('SERVICE_CATALOGUE_API_KEY'),
  'filter': os.getenv('SC_FILTER', ''),
}

sc = ServiceCatalogue(sc_params)
components = sc.get_all_records(sc.components_get)

for each_component in components:
  component_id = each_component['id']
  if 'environments' in each_component['attributes']:
    for each_environment in each_component['attributes'].get('environments'):
      if each_environment:
        sc.log.debug(json.dumps(each_environment, indent=2))
        print(
          f'{component_id}|{each_component.get("attributes").get("name")}|{each_environment.get("id")}|{each_environment.get("name")}|{each_environment.get("monitor")}'
        )

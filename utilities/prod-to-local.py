# This needs to be validated before use
# since it has been re-written to use Strapi v5 and
# hmpps-python-lib shared libraries

import os
import json
import logging

# hmpps
from hmpps import ServiceCatalogue
from hmpps.services.job_log_handling import log_debug, log_info

# service catalogue parameters
sc_in_params = {
  'url': os.getenv('SC_API_PROD_ENDPOINT'),
  'key': os.getenv('SC_API_PROD_KEY'),
  'filter': os.getenv('SC_FILTER', ''),
}

# service catalogue parameters
sc_out_params = {
  'url': os.getenv('SC_API_LOCAL_ENDPOINT'),
  'key': os.getenv('SC_API_LOCAL_KEY'),
  'filter': os.getenv('SC_FILTER', ''),
}


sc_in = ServiceCatalogue(sc_in_params)
sc_out = ServiceCatalogue(sc_out_params)

# github_teams = sc_in.get_all_records('github-teams')

tables = [
  'service-areas',
  'product-sets',
  (
    'products',
    sc_in.products_get,
    # Links to other table
    [
      ('product_set', 'product-sets'),
      ('service_area', 'service-areas'),
      ('team', 'teams'),
    ],
    # Subcomponents
    ['parent'],
  ),
  (
    'namespaces',
    'namespaces?populate[0]=elasticache_cluster&populate[1]=pingdom_check&populate[2]=rds_instance',
    [],
    ['elasticache_cluster', 'pingdom_check', 'rds_instance'],
  ),
  'teams',
  (
    'components',
    sc_in.components_get,
    [('product', 'products')],
    ['envs', 'latest_commit'],
  ),
]
for table in tables:
  subtables = []
  subcomponents = []
  if isinstance(table, tuple):
    in_table = table[0]
    query = table[1]
    subtables = table[2]
    subcomponents = table[3]
  else:
    in_table = table
    query = table

  records = sc_in.get_all_records(query)

  for record in records:
    log_debug(f'Dealing with {in_table} record: {json.dumps(record, indent=2)}')
    # Subtables
    for subtable in subtables:
      log_debug(f'Looking for links in {subtable}')
      subtable_link = subtable[0]
      subtable_name = subtable[1]
      # replace the subtable with just the ID
      subtable_record_id = None
      if subtable_data := record.get(subtable_link):
        log_debug(f'Found subtable data in {subtable_link}: {subtable_data}')
        if subtable_record_name := subtable_data.get('name'):
          subtable_record_id = sc_out.get_id(
            f'{subtable_name}', 'name', subtable_record_name
          )
          log_debug(
            f'Record ID found in {subtable_name} for {subtable_record_name}: {subtable_record_id}'
          )
      else:
        log_info(f'No subtable data in {subtable_link}')
      record[subtable_link] = subtable_record_id
    # Subcomponents
    for subcomponent in subcomponents:
      subcomponent_link = subcomponent
      subcomponent_name = record.get(subcomponent)
      if isinstance(subcomponent_name, dict):
        record['subcomponent_link'] = None
        if subcomponent_id := sc_out.get_id(
          f'{in_table}', 'name', subcomponent.get('name')
        ):
          log_debug(
            f'Record ID found in {in_table} for {subcomponent_name}: {subcomponent_id}'
          )
          record['subcomponent_link'] = subcomponent_id
      else:
        updated_subcomponent = []  # need to do something tricky here
        log_debug(f'Subcomponent time - {subcomponent_name}')
        log_debug(f'Attributes: {record}')
        for each_element in record.get(subcomponent):
          each_element.pop('documentId')
          if subcomponent == 'environments':  # add the namespace ID if possible
            if namespace_name := each_element.get('namespace'):
              if namespace_id := sc_out.get_id('namespaces', 'name', namespace_name):
                each_element['ns'] = namespace_id
          updated_subcomponent.append(each_element)
        record[subcomponent] = updated_subcomponent
        log_debug(f'Updated {subcomponent} is {updated_subcomponent}')
    # Update the record
    log_debug(f'{in_table}:\n{json.dumps(record, indent=2)}')
    if existing_id := sc_out.get_id(in_table, 'name', record.get('name')):
      sc_out.update(in_table, existing_id, record['attributes'])
    else:
      sc_out.add(in_table, record['attributes'])

records = sc_in.get_all_records('github-teams')
for record in records:
  if existing_id := sc_out.get_id('github-teams', 'team_name', record.get('team_name')):
    sc_out.update('github-teams', existing_id, record)
  else:
    sc_out.add('github-teams', record)

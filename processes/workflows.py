from time import sleep
from datetime import datetime, timezone
import threading
import yaml
import re
import json

# Standalone functions
from includes import standards
from includes.utils import update_dict, find_matching_keys
from includes.values import actions_whitelist
from utilities.job_log_handling import (
  log_debug,
  log_error,
  log_info,
  log_critical,
  log_warning,
)


# get non-standard actions (based on whitelist in values.py)
# This will return an ever growing dictionary of potentially duplicate actions
def get_non_local_actions(yml_data, actions, path):
  if uses := find_matching_keys(yml_data, 'uses'):
    log_debug(f'qty of uses in {path}: {len(uses)}')

    for value in uses:
      if not any(re.match(regex, value) for regex in actions_whitelist):
        log_debug(f'value: {value} (type: {type(value)})')
        try:
          name, ref = value.split('@')
          action = {name: {'ref': ref, 'path': path}}
          log_debug(f'Action found: {action}')
          actions.update(action)
        except ValueError:
          log_debug(f'Invalid format for action: {value}')

  return actions


######################################################
# Component Workfow Scanning - only runs once per week
######################################################


def process_sc_component_workflows(component, services, **kwargs):
  # Set some convenient defaults
  sc = services.sc
  gh = services.gh
  component_name = component['attributes']['name']
  github_repo = component['attributes']['github_repo']

  # Reset the data ready for updating
  data = {}  # dictionary to hold all the updated data for the component
  component_flags = {}
  non_local_actions = {}

  try:
    repo = gh.get_org_repo(f'{github_repo}')
  except Exception as e:
    log_error(
      f'ERROR accessing ministryofjustice/{repo.name}, check github app has permissions to see it. {e}'
    )

  # get the non-standard workflows
  try:
    workflow_dir = repo.get_contents(
      '.github', ref=repo.get_branch(repo.default_branch).commit.sha
    )
  except Exception as e:
    workflow_dir = None
    log_warning(f'Unable to load the workflows folder for {component_name}: {e}')

  while workflow_dir:
    file_content = workflow_dir.pop(0)
    log_debug(f'file_content.name: {file_content.name}')
    if file_content.type == 'dir':
      workflow_dir.extend(repo.get_contents(file_content.path))
    elif file_content.name.endswith(('.yaml', '.yml')):
      yml_content = file_content.decoded_content.decode()

      try:
        yml_data = yaml.safe_load(yml_content)
      except yaml.YAMLError as e:
        print(f'Error parsing {file_content.path}: {e}')
      if yml_data:
        # get non-standard actions
        non_local_actions = get_non_local_actions(
          yml_data, non_local_actions, file_content.path
        )
  # now the actions have been found, compare them with the existing actions stored in components
  if non_local_actions:
    # get the current versions list

    versions = component.get('attributes', {}).get('versions') or {}

    log_debug(
      f'non_local_actions for {component_name}: {json.dumps(non_local_actions, indent=2)}'
    )
    # Deduplicate the actions

    versions['actions'] = non_local_actions
    component_flags['qty_repos'] = True

    log_debug(f'Final versions list: {versions}')

    data['versions'] = versions

  # Update component with all results in data dictionary if there's data to do so
  if data:
    if not sc.update(sc.components, component['id'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags

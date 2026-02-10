import yaml
import re
import json

# hmpps
from hmpps.services.job_log_handling import (
  log_debug,
  log_error,
  log_warning,
)
from hmpps import find_matching_keys

# local
from includes.values import actions_allowlist


# get non-standard actions (based on whitelist in values.py)
# This will return an ever growing dictionary of potentially duplicate actions
def add_non_local_actions(yml_data, actions, path):
  if uses := find_matching_keys(yml_data, 'uses'):
    log_debug(f'qty of uses in {path}: {len(uses)}')

    for value in uses:
      if not any(re.match(regex, value) for regex in actions_allowlist):
        log_debug(f'value: {value} (type: {type(value)})')
        try:
          name, ref = value.split('@')
          action = {name: {'ref': ref, 'path': path}}
          log_debug(f'Action found: {action}')
          actions.update(action)
        except ValueError:
          log_debug(f'Invalid format for action: {value}')


# Scan the workflow directory (iterating where necessary)
# to find YAML files, then extract details of the workflows
def scan_for_local_actions(workflow_dir, repo):
  non_local_actions = {}
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
        continue
      if yml_data:
        # add to non-local actions diectionary
        add_non_local_actions(yml_data, non_local_actions, file_content.path)
  return non_local_actions


######################################################
# Component Workfow Scanning - only runs once per week
######################################################


def process_sc_component_workflows(services, component, **kwargs):
  # Set some convenient defaults
  sc = services.sc
  gh = services.gh
  component_name = component.get('name')
  github_repo = component.get('github_repo')

  # Reset the data ready for updating
  data = {}  # dictionary to hold all the updated data for the component
  component_flags = {}

  try:
    repo = gh.get_org_repo(f'{github_repo}')
  except Exception as e:
    log_error(
      f'ERROR accessing ministryofjustice/{github_repo},'
      f'check github app has permissions to see it. {e}'
    )
    component_flags['update_error'] = True
    return component_flags

  # get the non-standard workflows
  try:
    workflow_dir = repo.get_contents(
      '.github', ref=repo.get_branch(repo.default_branch).commit.sha
    )
  except Exception as e:
    log_warning(f'Unable to load the workflows folder for {component_name}: {e}')
    component_flags['update_error'] = True
    return component_flags

  # compare them with the existing actions stored in components
  if non_local_actions := scan_for_local_actions(workflow_dir, repo):
    # get the current versions list
    versions = component.get('versions', {}) or {}

    log_debug(
      f'non_local_actions for {component_name}: '
      f'{json.dumps(non_local_actions, indent=2)}'
    )
    # Deduplicate the actions

    versions['actions'] = non_local_actions
    component_flags['qty_repos'] = True

    log_debug(f'Final versions list: {versions}')

    data['versions'] = versions

  # Update component with all results in data dictionary if there's data to do so
  if data:
    if not sc.update(sc.components, component['documentId'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags

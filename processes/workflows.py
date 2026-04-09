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

# SHA is a 40-character hex string
_SHA_RE = re.compile(r'^[0-9a-f]{40}$')

# Pattern to extract SHA->version from YAML comment annotations, e.g.:
#   uses: owner/action@<40-char-sha> # v1.2.3
_SHA_COMMENT_RE = re.compile(r'uses:\s+\S+@([0-9a-f]{40})\s+#\s*(\S+)', re.MULTILINE)

# Module-level cache so SHA->version mappings discovered in one file or via the
# GitHub API are reused across all files and components processed in this run.
_sha_version_cache: dict[str, str] = {}


def _extract_sha_comments(yml_content):
  """Return a {sha: version} dict parsed from inline YAML comments."""
  return {m.group(1): m.group(2) for m in _SHA_COMMENT_RE.finditer(yml_content)}


def _lookup_sha_via_api(gh, action_name, sha):
  """Look up the version tag for a commit SHA via the GitHub API.

  Results are stored in _sha_version_cache to avoid repeated API calls.
  Returns the version string, or None if it cannot be determined.
  """
  if sha in _sha_version_cache:
    return _sha_version_cache[sha]

  try:
    parts = action_name.split('/')
    if len(parts) >= 2:
      repo = gh.session.get_repo(f'{parts[0]}/{parts[1]}')
      for tag in repo.get_tags():
        if tag.commit.sha == sha:
          _sha_version_cache[sha] = tag.name
          log_debug(f'Resolved {sha[:8]}... -> {tag.name} for {action_name}')
          return tag.name
  except Exception as e:
    log_debug(f'Unable to resolve SHA {sha[:8]}... for {action_name}: {e}')

  return None


def _is_reusable_workflow_reference(reference_name):
  """Return True when a uses target looks like a reusable workflow file."""
  # Reusable workflows are referenced by a workflow YAML file path.
  # Examples:
  # - owner/repo/.github/workflows/deploy.yml
  # - ./.github/workflows/deploy.yaml
  return reference_name.endswith(('.yml', '.yaml'))


def _split_actions_and_workflows(non_local_actions):
  """Split discovered uses references into action and workflow dictionaries."""
  actions = {}
  workflows = {}

  for name, details in non_local_actions.items():
    if _is_reusable_workflow_reference(name):
      workflows[name] = details
    else:
      actions[name] = details

  return actions, workflows


# get non-standard actions (based on whitelist in values.py)
# This will return an ever growing dictionary of potentially duplicate actions
def add_non_local_actions(yml_data, actions, path, yml_content=None, gh=None):
  # Build a SHA->version map from inline YAML comments for this file, and
  # merge any new discoveries into the shared module-level cache.
  if yml_content:
    discovered = _extract_sha_comments(yml_content)
    _sha_version_cache.update(discovered)

  if uses := find_matching_keys(yml_data, 'uses'):
    log_debug(f'qty of uses in {path}: {len(uses)}')

    for value in uses:
      if not any(re.match(regex, value) for regex in actions_allowlist):
        log_debug(f'value: {value} (type: {type(value)})')
        try:
          name, ref = value.split('@')
          if _SHA_RE.match(ref):
            # ref is a pinned SHA: store hash separately and resolve the version
            hash_val = ref
            version = _sha_version_cache.get(ref)
            if not version and gh:
              version = _lookup_sha_via_api(gh, name, ref)
            action = {
              name: {'ref': version or hash_val, 'hash': hash_val, 'path': path}
            }
          else:
            # ref is a normal version tag
            if len(ref) > 12:
              ref = f'{ref[:4]}...{ref[-4:]}'
            hash = ''
            action = {name: {'ref': ref, 'hash': hash, 'path': path}}
          log_debug(f'Action found: {action}')
          actions.update(action)
        except ValueError:
          log_debug(f'Invalid format for action: {value}')


# Scan the workflow directory (iterating where necessary)
# to find YAML files, then extract details of the workflows
def scan_for_local_actions(workflow_dir, repo, gh=None):
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
        log_error(f'Error parsing {file_content.path}: {e}')
        continue
      if yml_data:
        # add to non-local actions dictionary
        add_non_local_actions(
          yml_data,
          non_local_actions,
          file_content.path,
          yml_content=yml_content,
          gh=gh,
        )
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
  if non_local_actions := scan_for_local_actions(workflow_dir, repo, gh=gh):
    # get the current versions list
    versions = component.get('versions', {}) or {}
    actions, workflows = _split_actions_and_workflows(non_local_actions)

    log_debug(
      f'non_local_actions for {component_name}: '
      f'{json.dumps(non_local_actions, indent=2)}'
    )

    log_debug(
      f'Classified non-local uses for {component_name}: '
      f'actions={len(actions)}, workflows={len(workflows)}'
    )

    versions['Github Actions'] = actions
    versions['Github Workflows'] = workflows
    component_flags['qty_repos'] = True

    log_debug(f'Final versions list: {versions}')

    data['versions'] = versions

  # Update component with all results in data dictionary if there's data to do so
  if data:
    if not sc.update(sc.components, component['documentId'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags

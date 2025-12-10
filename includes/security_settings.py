import re

# hmpps
from hmpps import update_dict
from hmpps.services.job_log_handling import (
  log_debug,
  log_info,
  log_warning,
)

# Contains functions that return versions


def get_npmrc_config(gh, repo):
  """Parse .npmrc file and extract configuration settings."""
  npmrc_config = {}
  if npmrc_content := gh.get_file_plain(repo, '.npmrc'):
    try:
      # Parse each line looking for key = value pairs
      for line in npmrc_content.splitlines():
        # Skip comments and empty lines
        line = line.strip()
        if not line or line.startswith('#'):
          continue
        
        # Match "key = value" pattern
        if match := re.match(r'^\s*([a-zA-Z0-9_-]+)\s*=\s*(.+)\s*$', line):
          key, value = match.groups()
          npmrc_config[key] = value.strip()
      
      log_debug(f'Found npmrc_config: {npmrc_config}')
    except Exception as e:
      log_warning(f'Unable to parse .npmrc file - {e}')
      pass

  if npmrc_config:
    return npmrc_config
  else:
    log_debug('No .npmrc file found or no valid configuration')
  return None


def get_npmrc_ignore_scripts(services, repo):
  """Get the ignore-scripts setting from .npmrc."""
  if repo.language == 'JavaScript' or repo.language == 'TypeScript':
    if npmrc_config := get_npmrc_config(services.gh, repo):
      ignore_scripts_value = npmrc_config.get('ignore-scripts', '')
      # Convert to boolean if it's 'true' or 'false'
      if ignore_scripts_value.lower() == 'true':
        return True
      elif ignore_scripts_value.lower() == 'false':
        return False


# Main function that calls all the others
def get_security_settings(services, repo, component_project_dir, data):
  """Get security settings from various config files."""

  # NPM config
  if ignore_scripts := get_npmrc_ignore_scripts(services, repo):
    log_info(f'Updating npm ignore-scripts setting: {ignore_scripts}')
    update_dict(
      data,
      'security_settings',
      {'npm': {'ignore_scripts': ignore_scripts}},
    )
  else:
    log_debug(f'npm ignore-scripts setting not found for {repo.name}')

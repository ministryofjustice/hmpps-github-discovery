from time import sleep
from datetime import datetime, timezone
import threading

# Standalone functions
from includes import standards
from includes.utils import update_dict
from utilities.job_log_handling import (
  log_debug,
  log_error,
  log_info,
  log_critical,
  log_warning,
)

######################################################
# Component Security Scanning - only runs once per day
######################################################


def process_sc_component_security(component, services, **kwargs):
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
      f'ERROR accessing ministryofjustice/{repo.name}, check github app has permissions to see it. {e}'
    )

  # Codescanning Alerts
  #####################

  if codescanning_summary := gh.get_codescanning_summary(repo):
    update_dict(data, 'codescanning_summary', codescanning_summary)
    component_flags['repos_with_vulnerabilities'] = 1

  # Repository Standards
  #############################

  if repo_standards := standards.get_standards_compliance(repo):
    update_dict(data, 'standards_compliance', repo_standards)

  # Update component with all results in data dictionary if there's data to do so
  if data:
    if not sc.update(sc.components, component['documentId'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags

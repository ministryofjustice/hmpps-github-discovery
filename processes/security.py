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


# Repository variables - processed daily to ensure that the Service Catalogue is up-to-date
def get_repo_variables(services, repo, component_name):
  repo_vars = {}
  repo_var_list = [
    ('product', 'HMPPS_PRODUCT_ID'),
    ('slack_channel_security_scans_notify', 'SECURITY_ALERTS_SLACK_CHANNEL_ID'),
    ('slack_channel_prod_release_notify', 'PROD_RELEASES_SLACK_CHANNEL'),
    ('slack_channel_nonprod_release_notify', 'NONPROD_RELEASES_SLACK_CHANNEL'),
  ]
  for var in repo_var_list:
    try:
      repo_var = repo.get_variable(var[1])
      repo_var_value = repo_var.value
      if repo_var == 'HMPPS_PRODUCT_ID':
        if sc_product_id := services.sc.get_id('products', 'p_id', repo_var_value):
          repo_vars[var[0]] = sc_product_id
        else:
          repo_vars[var[0]] = repo_var.value
    except Exception as e:
      if e.status == 404:
        log_debug(f'No {var[1]} repo variable found for {component_name}')
      else:
        log_debug(f'Could not get {var[1]} repo variable for {component_name} - {e}')
      pass
  return repo_vars


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

  # Repository variables
  ######################
  if repo_variables := get_repo_variables(services, repo, component_name):
    data.update(repo_variables)

  # This will ensure the service catalogue has the latest collection of repository variables

  # Update component with all results in data dictionary if there's data to do so
  if data:
    if not sc.update(sc.components, component['documentId'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags

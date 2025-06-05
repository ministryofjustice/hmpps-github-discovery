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


def process_sc_component_security(component, services):
  # Set some convenient defaults
  sc = services.sc
  gh = services.gh
  component_name = component['attributes']['name']
  github_repo = component['attributes']['github_repo']

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
    component_flags['repos_with_vulnerabilities'] = (
      component_flags.get('repos_with_vulnerabilities', 0) + 1
    )

  # Repository Standards
  #############################

  if repo_standards := standards.get_standards_compliance(services, repo):
    update_dict(data, 'standards_compliance', repo_standards)

  # Update component with all results in data dictionary if there's data to do so
  if data:
    if not sc.update(sc.components, component['id'], data):
      log_error(f'Error updating component {component_name}')
      component_flags['update_error'] = True

  return component_flags


#############################################################################################################
# Main batch dispatcher - this is the process that's called by github_security_discovery
#############################################################################################################
def batch_process_sc_security_components(services, max_threads):
  sc = services.sc

  processed_components = []

  components = sc.get_all_records(sc.components_get)

  log_info(f'Processing batch of {len(components)} components...')

  threads = []
  component_count = 0
  for component in components:
    component_count += 1
    # Wait until the API limit is reset if we are close to the limit
    cur_rate_limit = services.gh.get_rate_limit()
    log_info(
      f'{component_count}/{len(components)} - preparing to process {component["attributes"]["name"]} ({int(component_count / len(components) * 100)}% complete)'
    )
    log_info(
      f'Github API rate limit {cur_rate_limit.remaining} / {cur_rate_limit.limit} remains -  resets at {cur_rate_limit.reset}'
    )
    while cur_rate_limit.remaining < 500:
      cur_rate_limit = services.gh.get_rate_limit()
      time_delta = cur_rate_limit.reset - datetime.now(timezone.utc)
      time_to_reset = time_delta.total_seconds()
      if int(time_to_reset) > 10 and cur_rate_limit.remaining < 500:
        log_info(
          f'Backing off for {time_to_reset + 10} seconds, to avoid github API limits.'
        )
        sleep(
          int(time_to_reset + 10)
        )  # Add a second to avoid irritating fractional settings

    # Mini function to process the component and store the result
    # because the threading needs to target a function
    def process_component_and_store_result(component, services):
      result = process_sc_component_security(component, services)
      processed_components.append((component['attributes']['name'], result))

    # Create a thread for each component
    t_repo = threading.Thread(
      target=process_component_and_store_result,
      args=(component, services),
      daemon=True,
    )
    threads.append(t_repo)

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (max_threads - 1):
      log_debug(f'Active Threads={threading.active_count()}, Max Threads={max_threads}')
      sleep(10)

    t_repo.start()
    log_info(f'Started thread for component {component["attributes"]["name"]}')

  # wait until all the threads are finished
  for t in threads:
    t.join()

  return processed_components

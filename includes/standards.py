# Repository standards
# This returns a dictionary object of compliance items
#
# Requires:
# - Github repository object

# Repository model based on the one from
# https://github.com/ministryofjustice/github-community/tree/main/app/projects/
#  repository_standards/models

# hmpps
from hmpps import RepositoryInfoFactory
from hmpps.services.job_log_handling import log_debug, log_info

# These are mapped to the RepositoryInfo model in models/repository_info.py

#######################################################################################
# get_standards_compliance
# This function will check the repository compliance
# against a number of criteria
# These criteria are stored in includes/values.py
#######################################################################################

# local
from includes.values import standards


def visibility_logic(repo_details):
  # internal (or private) by default
  # public if public-release-criteria-met
  visibility = repo_details.basic.visibility
  if visibility in ('private', 'internal'):
    return True
  if visibility == 'public':
    # GitHub returns true/false custom properties as strings
    custom_properties = repo_details.basic.custom_properties or {}
    criteria_met = custom_properties.get('public-release-criteria-met')
    return str(criteria_met).lower() == 'true'
  return False


def get_standards_compliance(repo):
  if repo_details := RepositoryInfoFactory.from_github_repo(repo):
    log_info(f'{repo_details}')
  else:
    return None

  data = {}

  # Custom standard for visibility, since it's nuanced:
  data['visibility'] = visibility_logic(repo_details)

  # Basic standards from the values files
  for standard in standards:
    data[standard[0]] = False
    repo_attr = repo_details
    # drill down into the subfields to get the data
    for attr_parts in standard[1].split('.'):
      repo_attr = getattr(repo_attr, attr_parts)
    log_debug(f'{standard} ({len(standard)}): {repo_attr}')
    if len(standard) > 2:
      # If there is a value, validate against it
      if isinstance(repo_attr, int) and not isinstance(repo_attr, bool):
        data[standard[0]] = repo_attr >= standard[2]
      elif isinstance(repo_attr, dict):
        # Custom properties: standard value is 'property-name|expected-value'
        prop_name, expected = standard[2].split('|', 1)
        prop_value = repo_attr.get(prop_name)
        if isinstance(prop_value, list):
          if expected in prop_value:
            data[standard[0]] = True
        elif prop_value == expected:
          data[standard[0]] = True
      else:
        # Exact match
        if repo_attr == standard[2]:
          data[standard[0]] = True
    else:
      if repo_attr:
        data[standard[0]] = True

  return data

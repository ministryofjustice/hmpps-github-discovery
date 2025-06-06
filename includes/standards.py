# Repository standards
# This returns a dictionary object of compliance items
#
# Requires:
# - Github repository object

# Repository model based on the one from
# https://github.com/ministryofjustice/github-community/tree/main/app/projects/repository_standards/models

from models.repository_info import (
  RepositoryInfoFactory,
)
from utilities.job_log_handling import log_debug, log_error, log_info, log_critical


# These are mapped to the RepositoryInfo model in models/repository_info.py

################################################################################################
# get_standards_compliance
# This function will check the repository compliance
# against a number of criteria
# These criteria are stored in includes/values.py
################################################################################################
from includes.values import standards


def get_standards_compliance(repo):
  repo_details = RepositoryInfoFactory.from_github_repo(repo)
  log_info(repo_details)

  data = {}
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
        if repo_attr >= standard[2]:
          data[standard[0]] = True
      else:
        if repo_attr == standard[2]:
          data[standard[0]] = True
    else:
      # if there isn't a value, just make sure it's not 'None'
      if repo_attr:
        data[standard[0]] = True
  return data

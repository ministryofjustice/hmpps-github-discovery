# Repository standards
# This returns a dictionary object of compliance items
#
# Requires:
# - Github repository object

# Repository model based on the one from
# https://github.com/ministryofjustice/github-community/tree/main/app/projects/repository_standards/models

# Standards are within the includes.values.py file

from models.repository_info import (
  RepositoryInfoFactory,
)
from includes.values import standards

################################################################################################
# get_compliance
# This function will check the repository compliance
# against a number of criteria
################################################################################################


def get_standards_compliance(services, repo):
  repo_details = RepositoryInfoFactory.from_github_repo(repo)
  services.log.info(repo_details)

  data = {}
  for standard in standards:
    data[standard[0]] = False
    repo_attr = repo_details
    # drill down into the subfields to get the data
    for attr_parts in standard[1].split('.'):
      repo_attr = getattr(repo_attr, attr_parts)
    services.log.debug(f'{standard} ({len(standard)}): {repo_attr}')
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

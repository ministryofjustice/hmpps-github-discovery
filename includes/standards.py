# Repository standards
# This returns a dictionary object of compliance items
#
# Requires:
# - Active github connection with access to repo
# - Component object data

# Checks (marked as True if compliant)
# =====================================
# repository_description: the repo description is not blank (mandatory)
# secret_scanning: secret scanning enabled (mandatory)
# push_protection: push protection enabled (mandatory)
# branch_protection_admins: default branch protection enforced for admins (mandatory)
# branch_protection_signed: default branch protection requires signed commits (optional)
# branch_protection_review: default branch protection requires code owner reviews (optional)
# pull_dismiss_stale_reviews: default branch pull request dismiss stale reviews (optional - may be mandatory in the future)
# pull_requires_review: default branch pull request requires at least one review (optional - may be mandatory in the future)
# authoritative_owner: has an authoritative owner (optional)
# licence_mit: license is MIT (optional)
# default_branch_main: Default Branch is Main (mandatory)
# issues_section_enabled: Issues section is enabled (optional)

################################################################################################
# get_compliance
# This function will check the repository compliance
# against a number of criteria
################################################################################################

standards = [
  'default_branch_main',
  'repository_description',
  'secret_scanning',
  'secret_scanning_push_protection',
  # 'branch_protection_admins',
  # 'branch_protection_signed',
  # 'branch_protection_review',
  # 'pull_dismiss_stale_reviews',
  # 'pull_requires_review',
  # 'authoritative_owner',
  # 'licence_mit',
  # 'issues_section_enabled'
]


def check_default_branch_main(services, repo, component):
  try:
    if repo.default_branch == 'main':
      services.log.debug('Default branch is "main"')
      return True
    else:
      services.log.debug('Default branch is not "main"')
      return False
  except Exception as e:
    services.log.error(f'Failed to get default branch information: {e}')
    return None


def check_repository_description(services, repo, component):
  try:
    if repo.description and len(repo.description) > 0:
      services.log.debug('Repo description is present')
      return True
    else:
      services.log.debug('No repo description')
      return False
  except Exception as e:
    services.log.error(f'Failed to get default branch information: {e}')
    return None


def check_secret_scanning(services, repo, component):
  try:
    secret_scanning_status = getattr(
      repo.security_and_analysis.secret_scanning_push_protection, 'status', None
    )
    if secret_scanning_status == 'enabled':
      services.log.debug('secret_scanning_push_protection is enabled')
      return True
    else:
      services.log.debug(f'secret_scanning is {secret_scanning_status}')
      return False

  except Exception as e:
    services.log.error(f'Failed to get secret scanning push protection status: {e}')
    return None


def check_secret_scanning_push_protection(services, repo, component):
  try:
    push_protection_status = getattr(
      repo.security_and_analysis.secret_scanning_push_protection, 'status', None
    )
    if push_protection_status == 'enabled':
      services.log.debug('secret_scanning_push_protection is enabled')
      return True
    else:
      services.log.debug(f'secret_scanning_push_protection is {push_protection_status}')
      return False

  except Exception as e:
    services.log.error(f'Failed to get secret scanning push protection status: {e}')
    return None

  # if result := services.gh.api_get(
  #   f'/repos/ministryofjustice/{repo.name}/security_and_analysis'
  # ):
  #   services.log.debug(f'result: {result}')
  #   if (
  #     result.get('secret_scanning', {}).get('push_protection', {}).get('status')
  #     == 'enabled'
  #   ):
  return True
  # else:
  #   return False


def get_standards_compliance(services, repo, component):
  data = {}
  for standard in standards:
    if standard_function := globals().get(f'check_{standard}'):
      data[standard] = standard_function(services, repo, component)
    else:
      services.log.error(f'Function {standard_function} not found')

  return data

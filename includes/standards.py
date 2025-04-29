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

# Standards compliance checks
# =====================================
# repository_description: the repo description is not blank (mandatory)
# secret_scanning: secret scanning enabled (mandatory for public repositories)
# push_protection: push protection enabled (mandatory for public repositories)
# branch_protection_admins: default branch protection enforced for admins (mandatory)
# branch_protection_signed: default branch protection requires signed commits (optional)
# branch_protection_code_owner_review: default branch protection requires code owner reviews (optional)
# pull_dismiss_stale_reviews: default branch pull request dismiss stale reviews (optional - may be mandatory in the future)
# pull_requires_review: default branch pull request requires at least one review (optional - may be mandatory in the future)
# authoritative_owner: has an authoritative owner (optional)
# licence_mit: license is MIT (optional)
# default_branch_main: Default Branch is Main (mandatory)
# issues_section_enabled: Issues section is enabled (optional)

# These are mapped to the RepositoryInfo model in models/repository_info.py

standards = [
  ('visibility_public', 'basic.visibility', 'public'),
  ('default_branch_main', 'basic.default_branch_name', 'main'),
  ('repository_description', 'basic.description'),
  ('secret_scanning', 'security_and_analysis.secret_scanning_status', 'enabled'),
  (
    'secret_scanning_push_protection',
    'security_and_analysis.push_protection_status',
    'enabled',
  ),
  ('branch_protection_admins', 'default_branch_protection.enforce_admins', True),
  ('branch_protection_signed', 'default_branch_protection.required_signatures', True),
  (
    'branch_protection_code_owner_review',
    'default_branch_protection.require_code_owner_reviews',
    True,
  ),
  (
    'pull_dismiss_stale_reviews',
    'default_branch_protection.dismiss_stale_reviews',
    True,
  ),
  (
    'pull_requires_review',
    'default_branch_protection.required_approving_review_count',
    1,
  ),
  ('authoritative_owner', 'basic.owner'),
  ('licence_mit', 'basic.license', 'mit'),
  ('issues_section_enabled', 'basic.has_issues', True),
]

################################################################################################
# get_standards_compliance
# This function will check the repository compliance
# against a number of criteria
################################################################################################


def get_standards_compliance(services, repo):
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

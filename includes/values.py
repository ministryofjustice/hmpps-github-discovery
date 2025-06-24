# File containing values for processes that need them

# Mapping of environment names to the values used in the service discovery URLs
env_mapping = {
  'staging': 'stage',
  'uat': 'stage',
  'stage': 'stage',
  'test': 'stage',
  'demo': 'test',
  'dev': 'dev',
  'development': 'dev',
  'preprod': 'preprod',
  'preproduction': 'preprod',
  'production': 'prod',
  'prod': 'prod',
}

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

# A list of whitelisted Github Actions providers - any that are not in this list will be included in the scan output.
actions_allowlist = [
  '^\\./\\.github',
  '^\\.github\\/',
  # '^ministryofjustice\\/',
  # '^docker\\/',
  # '^actions\\/',
  # '^slackapi\\/',
  # '^github\\/',
  # '^aquasecurity\\/',
  # '^azure\\/',
]

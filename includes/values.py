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

actions_whitelist = [
  '^\\./\\.github',
  '^\\.github\\/',
  '^ministryofjustice\\/',
  '^docker\\/',
  '^actions\\/',
  '^slackapi\\/',
  '^github\\/',
  '^aquasecurity\\/',
  '^azure\\/',
]

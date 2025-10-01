import os

# hmpps
from hmpps import GithubSession

gh_params = {
  'app_id': int(os.getenv('GITHUB_APP_ID')),
  'app_installation_id': int(os.getenv('GITHUB_APP_INSTALLATION_ID')),
  'app_private_key': os.getenv('GITHUB_APP_PRIVATE_KEY'),
}
gh = GithubSession(gh_params)
print(gh.get_rate_limit())

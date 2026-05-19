GITHUB_API_BASE_URL = 'https://api.github.com'
GITHUB_API_VERSION = '2026-03-10'
GITHUB_ACCEPT_HEADER = 'application/vnd.github+json'


def get_github_api_headers(token):
  return {
    'Authorization': f'Bearer {token}',
    'Accept': GITHUB_ACCEPT_HEADER,
    'X-GitHub-Api-Version': GITHUB_API_VERSION,
  }
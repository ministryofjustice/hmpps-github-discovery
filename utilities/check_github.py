import os

# hmpps
from hmpps import GithubSession

gh = GithubSession()
print(gh.get_rate_limit())

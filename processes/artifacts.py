import io
import json
import os
import zipfile
import requests
from hmpps.services.job_log_handling import log_debug, log_info, log_warning, log_error
from includes.github_api import GITHUB_API_BASE_URL, get_github_api_headers

DEFAULT_ARTIFACT_NAME = 'prod-deploy-details'
DEFAULT_TARGET_FILE = 'prod-ip-allowlist-version-details.json'

class ArtifactDetailsFetcher:
  def __init__(self, services, repo):
    self.api = GITHUB_API_BASE_URL
    self.headers = get_github_api_headers(services.gh.rest_token)
    self.artifact_name = os.getenv('ARTIFACT_NAME', DEFAULT_ARTIFACT_NAME)
    self.target_file = os.getenv('TARGET_FILE', DEFAULT_TARGET_FILE)
    self.repo_full_name = getattr(repo, 'full_name', f'ministryofjustice/{repo.name}')

  def get_latest_artifact(self):
    try:
      response = requests.get(
        f'{self.api}/repos/{self.repo_full_name}/actions/artifacts',
        headers=self.headers,
        params={'per_page': 100},
        timeout=20,
      )
      response.raise_for_status()
      data = response.json()
    except Exception as e:
      log_warning(f'Unable to get artifacts for {self.repo_full_name}: {e}')
      return None

    artifacts = data.get('artifacts', [])
    log_debug(
      f'Artifacts returned for {self.repo_full_name} (count={len(artifacts)}): '
      f'{[(a.get("id"), a.get("name"), a.get("expired"), a.get("created_at")) for a in artifacts]}'
    )

    for artifact in artifacts:
      if artifact.get('name') == self.artifact_name:
        return artifact

    return None

  def get_prod_ip_allowlist_details(
    self,
    existing_digest_sha=None,
    existing_ip_allowlist_version=None,
  ):
    artifact = self.get_latest_artifact()
    if not artifact:
      log_info(
        f'No artifact named {self.artifact_name} found for {self.repo_full_name}'
      )
      return None

    artifact_id = int(artifact.get('id'))
    artifact_digest = artifact.get('digest')
    log_debug(
      f'Found artifact {self.artifact_name} with ID {artifact_id} for {self.repo_full_name}'
    )

    if (
      artifact_digest
      and existing_digest_sha
      and artifact_digest == existing_digest_sha
    ):
      log_debug(
        f'Artifact digest unchanged for {self.repo_full_name}; '
        f'skipping artifact zip download'
      )
      return {
        'ip_allowlist_version': existing_ip_allowlist_version,
        'ip_allowlist_digest_sha': existing_digest_sha,
      }

    try:
      response = requests.get(
        f'{self.api}/repos/{self.repo_full_name}/actions/artifacts/{artifact_id}/zip',
        headers=self.headers,
        timeout=20,
      )
      response.raise_for_status()
      zip_bytes = response.content
    except Exception as e:
      log_warning(
        f'Unable to download artifact {artifact_id} for {self.repo_full_name}: {e}'
      )
      return None

    details = extract_target_file_from_zip_bytes(zip_bytes, self.target_file)
    if details and isinstance(details, dict):
      ip_allowlist_version = details.get('allowlist_version')
      if not ip_allowlist_version:
        log_info(
          f'No ip_allowlist_version field found in {self.target_file} for {self.repo_full_name}'
        )
        return None

      log_debug(
        f'Fetched {self.target_file} from artifact {artifact_id} for {self.repo_full_name}'
      )
      return {
        'ip_allowlist_version': ip_allowlist_version,
        'ip_allowlist_digest_sha': artifact_digest,
      }
    else:
      log_info(
        f'No {self.target_file} found in artifact {artifact_id} for {self.repo_full_name}'
      )

    return None


def extract_target_file_from_zip_bytes(zip_bytes, target_file):
  try:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_ref:
      for name in zip_ref.namelist():
        if name.endswith(target_file):
          with zip_ref.open(name, 'r') as target_handle:
            file_contents = target_handle.read().decode('utf-8', errors='replace').strip()
            if target_file.lower().endswith('.json'):
              try:
                return json.loads(file_contents)
              except json.JSONDecodeError as e:
                log_warning(f'Invalid JSON in target file {target_file}: {e}')
                return None
            return file_contents
  except zipfile.BadZipFile as e:
    log_warning(f'Downloaded artifact zip is invalid for target file {target_file}: {e}')

  return None


def update_prod_ip_allowlist_version_details(services, repo, data):
  log_info(f'Attempting to update prod IP allowlist version details for {repo.name}')
  try:
    if prod_ip_allowlist_details := ArtifactDetailsFetcher(
      services, repo
    ).get_prod_ip_allowlist_details(
      existing_digest_sha=data.get('ip_allowlist_digest_sha'),
      existing_ip_allowlist_version=data.get('ip_allowlist_version'),
    ):
      data['ip_allowlist_version'] = prod_ip_allowlist_details['ip_allowlist_version']
      data['ip_allowlist_digest_sha'] = prod_ip_allowlist_details['ip_allowlist_digest_sha']
      return True
  except Exception as e:
    log_error(
      f'Unexpected error setting prod ip allowlist version details for {repo.name}: {e}'
    )

  return False

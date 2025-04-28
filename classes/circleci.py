import requests
import logging
from includes.utils import update_dict
from utilities.error_handling import log_critical

class CircleCI:
  def __init__(self, params, log_level=logging.INFO):
    # Needs custom logging because of a bit of a mess later on
    logging.basicConfig(
      format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=log_level
    )
    self.log_level = log_level
    self.log = logging.getLogger(__name__)
    self.url = params['url']
    self.headers = {
      'Circle-Token': params['token'],
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    }

  def test_connection(self):
    try:
      response = requests.get(
        f'{self.url}hmpps-project-bootstrap', headers=self.headers, timeout=10
      )
      response.raise_for_status()
      self.log.info(f'CircleCI API: {response.status_code}')
      return True
    except Exception as e:
      log_critical(f'Unable to connect to the CircleCI API: {e}')
      return None

  def get_trivy_scan_json_data(self, project_name):
    self.log.debug(f'Getting trivy scan data for {project_name}')

    project_url = f'{self.url}{project_name}'
    output_json_content = {}
    try:
      response = requests.get(project_url, headers=self.headers, timeout=30)
      artifacts_url = None
      for build_info in response.json():
        workflows = build_info.get('workflows', {})
        workflow_name = workflows.get('workflow_name', {})
        job_name = build_info.get('workflows', {}).get('job_name')
        if workflow_name == 'security' and job_name == 'hmpps/trivy_latest_scan':
          latest_build_num = build_info['build_num']
          artifacts_url = f'{project_url}/{latest_build_num}/artifacts'
          break

      if artifacts_url:
        self.log.debug('Getting artifact URLs from CircleCI')
        response = requests.get(artifacts_url, headers=self.headers, timeout=30)

        artifact_urls = response.json()
        if output_json_url := next(
          (
            artifact['url']
            for artifact in artifact_urls
            if 'results.json' in artifact['url']
          ),
          None,
        ):
          self.log.debug('Fetching artifacts from CircleCI data')
          # do not use DEBUG logging for this request
          logging.getLogger('urllib3').setLevel(logging.INFO)
          response = requests.get(output_json_url, headers=self.headers, timeout=30)
          logging.getLogger('urllib3').setLevel(self.log_level)
          output_json_content = response.json()

    except Exception as e:
      self.log.debug(f'Error: {e}')

    return output_json_content

  def get_circleci_orb_version(self, circleci_config):
    versions_data = {}
    try:
      cirleci_orbs = circleci_config['orbs']
      for key, value in cirleci_orbs.items():
        if 'ministryofjustice/hmpps' in value:
          hmpps_orb_version = value.split('@')[1]
          update_dict(versions_data, 'circleci', {'hmpps_orb': hmpps_orb_version})
          self.log.debug(f'hmpps orb version: {hmpps_orb_version}')
    except Exception:
      self.log.debug('No hmpps orb version found')
    return versions_data

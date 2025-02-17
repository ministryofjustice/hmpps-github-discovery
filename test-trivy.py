from classes.service_catalogue import ServiceCatalogue
import os
import json
import logging

log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
  format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=log_level
)
log = logging.getLogger(__name__)

# service catalogue parameters
sc_params = {
  'url': os.getenv('SERVICE_CATALOGUE_LOCAL_API_ENDPOINT'),
  'key': os.getenv('SERVICE_CATALOGUE_LOCAL_API_KEY'),
  'filter': os.getenv('SC_FILTER', ''),
}

sc = ServiceCatalogue(sc_params)

# github_teams = sc_in.get_all_records('github-teams')

data = {
  'trivy_scan_results': {'Failures': 9, 'Severity': 10},
  'trivy_scan_timestamp': '2022-03-14T12:00:00Z',
  'build_image_tag': 'latest',
  'name': 'this-component-dev',
}
# records = sc.get_all_records('trivy-scans')
# print(f'{records}')
sc.add('trivy-scans', data)

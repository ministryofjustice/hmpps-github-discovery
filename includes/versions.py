import re
from dockerfile_parse import DockerfileParser
import io
import json
import tomllib

# hmpps
from hmpps import update_dict
from hmpps.services.job_log_handling import (
  log_debug,
  log_error,
  log_info,
  log_warning,
)

# local
from includes.utils import remove_version

# Contains functions that return versions


# Information from CircleCI data
################################


def get_circle_ci_orb_version(services, repo):
  circle_ci_config = '.circleci/config.yml'
  versions_data = {}
  if circleci_config := services.gh.get_file_yaml(repo, circle_ci_config):
    # CircleCI Orb version
    cirleci_orbs = circleci_config.get('orbs', {})
    for key, value in cirleci_orbs.items():
      if 'ministryofjustice/hmpps' in value:
        hmpps_orb_version = value.split('@')[1]
        update_dict(
          versions_data,
          'circleci',
          {'hmpps_orb': {'ref': hmpps_orb_version, 'path': circle_ci_config}},
        )
        log_info(f'hmpps orb version: {hmpps_orb_version}')
  return versions_data


def get_gradle_config(gh, repo):
  # get_gradle_config - reads the gradle file to determine versions
  gradle_config = {}
  if build_gradle_config_content := gh.get_file_plain(
    repo, 'build.gradle.kts'
  ) or gh.get_file_plain(repo, 'build.gradle'):
    try:
      regex = r'id\([\'"]uk\.gov\.justice\.hmpps\.gradle-spring-boot[\'"]\) version [\'"](.*)[\'"]( apply false)?$'
      if hmpps_gradle_spring_boot_matches := re.findall(
        regex, build_gradle_config_content, re.MULTILINE
      ):
        for version, apply_false in hmpps_gradle_spring_boot_matches:
          # if apply false is there, it will skip it
          if not apply_false:
            gradle_config['spring_boot_version'] = version
            break

    except TypeError as e:
      log_warning(f'Unable to parse build gradle file - {e}')
      pass

  if gradle_config:  # If there are some valid entries, happy days
    log_debug(f'Found hmpps gradle_config: {gradle_config}')
    return gradle_config
  else:
    log_info(
      'Unable to find gradle-spring-boot version within build.gradle.kts or build.gradle'
    )
  return None


# Gradle config
###############
def get_gradle_version(services, repo):
  if repo.language == 'Kotlin' or repo.language == 'Java':
    if gradle_config := get_gradle_config(services.gh, repo):
      return gradle_config.get('spring_boot_version', '')
  log_info(f'No valid gradle config found for {repo.name} - removing version info')
  return None


# Dockerfile reader
def get_dockerfile_data(dockerfile_contents):
  # Use an in-memory text buffer that can accept both str and bytes writes from DockerfileParser
  class _DockerfileStringIO(io.StringIO):
    def write(self, s):  # type: ignore[override]
      if isinstance(s, bytes):
        s = s.decode('utf-8')
      return super().write(s)

  temp_file = _DockerfileStringIO()
  if isinstance(dockerfile_contents, bytes):
    dockerfile_str = dockerfile_contents.decode('utf-8')
  else:
    dockerfile_str = dockerfile_contents
  dockerfile = DockerfileParser(fileobj=temp_file)  # type: ignore[arg-type]
  dockerfile.content = dockerfile_str

  docker_data = {}
  if re.search(r'rsds-ca-2019-root\.pem', dockerfile.content, re.MULTILINE):
    docker_data['rds_ca_cert'] = {'rds-ca-2019-root.pem'}
  if re.search(r'global-bundle\.pem', dockerfile.content, re.MULTILINE):
    docker_data['rds_ca_cert'] = 'rds-ca-2019-root.pem'

  try:
    # Get list of parent images, and strip out references to 'base'
    parent_images = list(filter(lambda i: i != 'base', dockerfile.parent_images))
    # Get the last element in the array, which should be the base image of the final stage.
    base_image = parent_images[-1]
    docker_data['base_image'] = base_image
    log_debug(f'Found Dockerfile base image: {base_image}')
  except Exception as e:
    log_error(f'Error parent/base image from Dockerfile: {e}')
  return docker_data


# Dockerfile
############
def get_docker_versions(services, repo, component_project_dir):
  docker_versions = {}
  dockerfile_path = f'{component_project_dir}/Dockerfile'
  log_debug(f'Looking for Dockerfile at {dockerfile_path}')
  if dockerfile_contents := services.gh.get_file_plain(repo, dockerfile_path):
    if docker_data := get_dockerfile_data(dockerfile_contents):
      # Reprocess the dictionary to include the path name
      for key, value in docker_data.items():
        docker_versions[key] = {'ref': value, 'path': dockerfile_path}
  return docker_versions


# Python (uv.lock)
def get_python_versions(services, repo):
  uv_lock = 'uv.lock'
  python_versions = {}
  if pyproject_toml_contents := services.gh.get_file_plain(repo, uv_lock):
    toml_data = tomllib.loads(pyproject_toml_contents)

    for pkg in toml_data.get('package', []):
      name = pkg.get('name')
      version = pkg.get('version')
      if name and version:
        python_versions[name] = {'ref': version, 'path': uv_lock}
  return python_versions


# Main function that calls all the others
def get_versions(services, repo, component_project_dir, data):
  # CircleCI
  if circleci_orb_version := get_circle_ci_orb_version(services, repo):
    log_info(f'Updating CircleCI version: {circleci_orb_version}')
    update_dict(data, 'versions', circleci_orb_version)
  else:
    log_info(f'No CircleCI version found for {repo.name}')

  # Gradle
  if spring_boot_version := get_gradle_version(services, repo):
    log_info(f'Updating Gradle Spring Boot version: {spring_boot_version}')
    update_dict(
      data,
      'versions',
      {'gradle': {'hmpps_gradle_spring_boot': spring_boot_version}},
    )
  else:
    log_info(f'Spring Boot version not found for {repo.name}')
    remove_version(data, 'gradle')

  # Docker
  if docker_versions := get_docker_versions(services, repo, component_project_dir):
    log_info(f'Docker versions: {json.dumps(docker_versions, indent=2)}')
    update_dict(data, 'versions', {'dockerfile': docker_versions})
  else:
    log_info(f'No Docker version information found for {repo.name}')
    remove_version(data, 'dockerfile')

  # Pyproject.toml
  if python_versions := get_python_versions(services, repo):
    log_info(f'Python versions: {json.dumps(python_versions, indent=2)}')
    update_dict(data, 'versions', {'python': python_versions})
  else:
    log_info(f'No Python version information found for {repo.name}')
    remove_version(data, 'python')

  return data

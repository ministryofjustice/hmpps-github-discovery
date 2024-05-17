#!/usr/bin/env python
'''Github discovery - queries the github API for info about hmpps services and stores the results in the service catalogue'''
import os
import http.server
import socketserver
import threading
import logging
import tempfile
from time import sleep
from datetime import datetime
from base64 import b64decode
import re
import json
import yaml
import github
import requests
from dockerfile_parse import DockerfileParser

SC_API_ENDPOINT = os.getenv("SERVICE_CATALOGUE_API_ENDPOINT")
SC_API_TOKEN = os.getenv("SERVICE_CATALOGUE_API_KEY")
GITHUB_APP_ID = int(os.getenv("GITHUB_APP_ID"))
GITHUB_APP_INSTALLATION_ID = int(os.getenv("GITHUB_APP_INSTALLATION_ID"))
GITHUB_APP_PRIVATE_KEY = os.getenv("GITHUB_APP_PRIVATE_KEY")
REFRESH_INTERVAL_HOURS = int(os.getenv("REFRESH_INTERVAL_HOURS", "6"))
CIRCLECI_TOKEN = os.getenv("CIRCLECI_TOKEN")
CIRCLECI_API_ENDPOINT = os.getenv("CIRCLECI_API_ENDPOINT")

# Set maximum number of concurrent threads to run, try to avoid secondary github api limits.
MAX_THREADS = 10
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

# limit results for testing/dev
# See strapi filter syntax https://docs.strapi.io/dev-docs/api/rest/filters-locale-publication
# Example filter string = '&filters[name][$contains]=example'
SC_FILTER = os.getenv("SC_FILTER", '')
SC_PAGE_SIZE = 10
SC_PAGINATION_PAGE_SIZE = f"&pagination[pageSize]={SC_PAGE_SIZE}"
# Example Sort filter
# SC_SORT='&sort=updatedAt:asc'
SC_SORT = ''
SC_ENDPOINT = f"{SC_API_ENDPOINT}/v1/components?populate=environments{SC_FILTER}{SC_PAGINATION_PAGE_SIZE}{SC_SORT}"


class HealthHttpRequestHandler(http.server.SimpleHTTPRequestHandler):
  def do_GET(self):
    self.send_response(200)
    self.send_header("Content-type", "text/plain")
    self.end_headers()
    self.wfile.write(bytes("UP", "utf8"))
    return


def update_sc_component(c_id, data):
  try:
    log.debug(data)
    x = requests.put(f"{SC_API_ENDPOINT}/v1/components/{c_id}", headers=sc_api_headers, json={"data": data}, timeout=10)
    if x.status_code == 200:
      log.info(f"Successfully updated component id {c_id}: {x.status_code}")
    else:
      log.info(f"Received non-200 response from service catalogue for component id {c_id}: {x.status_code} {x.content}")
  except Exception as e:
    log.error(f"Error updating component in the SC: {e}")


def get_file_yaml(repo, path):
  try:
    file_contents = repo.get_contents(path)
    contents = b64decode(file_contents.content).decode().replace("\t", "  ")
    yaml_contents = yaml.safe_load(contents)
    return yaml_contents
  except github.UnknownObjectException:
    log.debug(f"404 File not found {repo.name}:{path}")
  except Exception as e:
    log.error(f"Error getting yaml file: {e}")


def get_file_json(repo, path):
  try:
    file_contents = repo.get_contents(path)
    json_contents = json.loads(b64decode(file_contents.content))
    return json_contents
  except github.UnknownObjectException:
    log.debug(f"404 File not found {repo.name}:{path}")
  except Exception as e:
    log.error(f"Error getting json file: {e}")


def get_file_plain(repo, path):
  try:
    file_contents = repo.get_contents(path)
    plain_contents = b64decode(file_contents.content).decode()
    return plain_contents
  except github.UnknownObjectException:
    log.debug(f"404 File not found {repo.name}:{path}")
    return False
  except Exception as e:
    log.error(f"Error getting contents from file: {e}")


def test_endpoint(url, endpoint):
  headers = {'User-Agent': 'hmpps-service-discovery'}
  try:
    r = requests.get(f"{url}{endpoint}", headers=headers, allow_redirects=False, timeout=10)
    # Test if json is returned
    if r.json() and r.status_code != 404:
      log.debug(f"Found endpoint: {url}{endpoint} ")
      return True
  except Exception:
    log.debug(f"Couldn't connect to endpoint: {url}{endpoint} ")
    return False


def test_swagger_docs(url):
  headers = {'User-Agent': 'hmpps-service-discovery'}
  try:
    r = requests.get(f"{url}/swagger-ui.html", headers=headers, allow_redirects=False, timeout=10)
    # Test for 302 redirect)
    if r.status_code == 302 and ("/swagger-ui/index.html" in r.headers['Location'] or "api-docs/index.html" in r.headers['Location']):
      log.debug(f"Found swagger docs: {url}/swagger-ui.html")
      return True
  except Exception:
    log.debug(f"Couldn't connect: {url}/swagger-ui.html")
    return False


def test_subject_access_request_endpoint(url):
  headers = {'User-Agent': 'hmpps-service-discovery'}
  try:
    r = requests.get(f"{url}/v3/api-docs", headers=headers, allow_redirects=False, timeout=10)
    if r.status_code == 200:
      try:
        if r.json()['paths']['/subject-access-request']:
          log.debug(f"Found SAR endpoint at: {url}/v3/api-docs")
          return True
      except KeyError:
        log.debug("No SAR endpoint found.")
        return False
  except Exception:
    log.debug(f"Couldn't connect: {url}/v3/api-docs {r.status_code}")
    return False


def get_sc_id(match_type, match_field, match_string):
  try:
    r = requests.get(f"{SC_API_ENDPOINT}/v1/{match_type}?filters[{match_field}][$eq]={match_string}", headers=sc_api_headers, timeout=10)
    if r.status_code == 200 and r.json()['data']:
      sc_id = r.json()['data'][0]['id']
      log.info(f"Successfully found ID {sc_id}, matching type/field/string: {match_type}/{match_field}/{match_string}")
      return sc_id
    log.info(f"Could not find ID, matching type/field/string: {match_type}/{match_field}/{match_string}")
    return False
  except Exception as e:
    log.error(f"Error getting ID from SC: {e} - {r.status_code} {r.content}")
    return False
# This method is to find the values defined for allowlist in values*.yaml files under helm_deploy folder of each project.
# This methods read all the values files under helm_deploy folder and create a dictionary object of allowlist for each environment
# including the default values.


def fetch_values_for_allowlist_key(yaml_data, key):
  values = {}
  if isinstance(yaml_data, dict):
    if key in yaml_data:
      if isinstance(yaml_data[key], dict):
        values.update(yaml_data[key])
      else:
        values[key] = yaml_data[key]
    for k, v in yaml_data.items():
      if isinstance(v, (dict, list)):
        child_values = fetch_values_for_allowlist_key(v, key)
        if child_values:
          values.update({k: child_values})
  elif isinstance(yaml_data, list):
    for item in yaml_data:
      child_values = fetch_values_for_allowlist_key(item, key)
      if child_values:
        values.update(child_values)

  return values

# This method read the value stored in dictionary passed to it checks if the ip allow list is present or not and returns boolean


def is_ipallowList_enabled(yaml_data):
  ip_allow_list_enabled = False
  if isinstance(yaml_data, dict):
    for value in yaml_data.values():
      if isinstance(value, dict) and value:
        ip_allow_list_enabled = True
  return ip_allow_list_enabled

def get_trivy_scan_json_data(project_name):     
  circleci_headers = {"Authorization": f"Circle-Token: {CIRCLECI_TOKEN}", "Content-Type": "application/json", "Accept": "application/json"}
  project_url = f"{CIRCLECI_API_ENDPOINT}"+ project_name
  output_json_content={}
  try:
    response = requests.get(project_url, headers=circleci_headers)  
    for build_info in response.json():
      workflows = build_info.get('workflows',{})
      workflow_name = workflows.get('workflow_name',{})
      job_name = build_info.get('workflows',{}).get('job_name')
      if workflow_name == 'security' and job_name == 'hmpps/trivy_latest_scan':
        latest_build_num = build_info['build_num'] 
        artifacts_url = f"{project_url}/{latest_build_num}/artifacts" 
        break
    response = requests.get(artifacts_url, headers=circleci_headers) 
    artifact_urls = response.json()                     
    output_json_url = next((artifact['url'] for artifact in artifact_urls if 'results.json' in artifact['url']), None)
    if output_json_url:
      response = requests.get(output_json_url, headers=circleci_headers) 
      output_json_content = response.json()
    return output_json_content
  except Exception as e:
        log.debug(f"Error: {e}")
         
       


def process_repo(**component):

  allow_list_key = "allowlist"
  c_name = component["attributes"]["name"]
  c_id = component["id"]
  github_repo = component["attributes"]["github_repo"]
  part_of_monorepo = component["attributes"]["part_of_monorepo"]
  if part_of_monorepo:
    monorepo_dir_suffix = f"{c_name}/"
  else:
    monorepo_dir_suffix = ""

  log.info(f"Processing component: {c_name}")
  try:
    repo = gh.get_repo(f"ministryofjustice/{github_repo}")
    default_branch = repo.get_branch(repo.default_branch)
    branch_protection = default_branch.get_protection()
  except Exception as e:
    log.error(f"Error with ministryofjustice/{c_name}, check github app has permissions to see it. {e}")
    return False

  # Empty data dict gets populated along the way, and finally used in PUT request to service catalogue
  data = {}

  # Add standard github repo properties
  data.update({"language": repo.language})
  data.update({"description": repo.description})
  data.update({"github_project_visibility": repo.visibility})
  data.update({"github_repo": repo.name})

  # GitHub teams access, branch protection etc.
  branch_protection_restricted_teams = []
  teams_write = []
  teams_admin = []
  teams_maintain = []
  # variables used for implemenmtation of findind IP allowlist in helm values files
  ip_allow_list_data = {}
  ip_allow_list = {}
  ip_allow_list_default = {}

  try:
    branch_protection = default_branch.get_protection()
    branch_protection_teams = branch_protection.get_team_push_restrictions() or []
    for team in branch_protection_teams:
      branch_protection_restricted_teams.append(team.slug)
  except Exception as e:
    log.error(f"Unable to get branch protection {repo.name}: {e}")

  teams = repo.get_teams()
  for team in teams:
    team_permissions = team.get_repo_permission(repo)
    if team_permissions.admin:
      teams_admin.append(team.slug)
    elif team_permissions.maintain:
      teams_maintain.append(team.slug)
    elif team_permissions.push:
      teams_write.append(team.slug)

  data.update({"github_project_teams_admin": teams_admin})
  log.debug(f"teams_admin: {teams_admin}")

  data.update({"github_project_teams_maintain": teams_maintain})
  log.debug(f"teams_maintain: {teams_maintain}")

  data.update({"github_project_teams_write": teams_write})
  log.debug(f"teams_write: {teams_write}")

  data.update({"github_project_branch_protection_restricted_teams": branch_protection_restricted_teams})
  log.debug(f"branch_protection_restricted_teams: {branch_protection_restricted_teams}")

  # Github topics
  topics = repo.get_topics()
  data.update({"github_topics": topics})

  # Try to detect frontends or UIs
  if re.search("([fF]rontend)|(-ui)|(UI)|([uU]ser\s[iI]nterface)", f"{c_name} {repo.description}"):
    log.debug("Detected 'frontend|-ui' keyword, setting frontend flag.")
    data.update({"frontend": True})

  versions_data = {}
  trivy_scan_summary = {} 
  # CircleCI config
  cirlcleci_config = get_file_yaml(repo, ".circleci/config.yml")
  if cirlcleci_config:
    try:
      trivy_scan_json = get_trivy_scan_json_data(c_name) 
      trivy_scan_date = trivy_scan_json.get("CreatedAt")
      trivy_scan_summary.update({"trivy_scan_json": trivy_scan_json, "trivy_scan_date" : trivy_scan_date}) 
      # Add trivy scan result to final data dict.
      data.update({'trivy_scan_summary': trivy_scan_summary.get("trivy_scan_json")})
      data.update({'trivy_last_completed_scan_date': trivy_scan_summary.get("trivy_scan_date")})

      cirleci_orbs = cirlcleci_config['orbs']
      for key, value in cirleci_orbs.items():
        if "ministryofjustice/hmpps" in value:
          hmpps_orb_version = value.split('@')[1]
          versions_data.update({'circleci': {'hmpps_orb': hmpps_orb_version}})
          log.debug(f"hmpps orb version: {hmpps_orb_version}")
    except Exception:
      log.debug('No hmpps orb version found')

  # Helm charts
  helm_chart = get_file_yaml(repo, f"{monorepo_dir_suffix}helm_deploy/{c_name}/Chart.yaml") or {}
  if 'dependencies' in helm_chart:
    helm_dep_versions = {}
    for item in helm_chart['dependencies']:
      helm_dep_versions.update({item['name']: item['version']})
    versions_data.update({'helm_dependencies': helm_dep_versions})

  helm_environments = []
  try:
    helm_deploy = repo.get_contents(f"{monorepo_dir_suffix}helm_deploy", default_branch.commit.sha)
  except Exception as e:
    helm_deploy = False
    log.debug(f"helm_deploy folder: {e}")

  if helm_deploy:
    for file in helm_deploy:
      if file.name.startswith('values-'):
        env = re.match('values-([a-z0-9-]+)\\.y[a]?ml', file.name)[1]
        helm_environments.append(env)

        # HEAT-223 Start : Read and collate data for IPallowlist from all environment specific values.yaml files.
        ip_allow_list[file] = fetch_values_for_allowlist_key(get_file_yaml(repo, f"{monorepo_dir_suffix}helm_deploy/{file.name}"), allow_list_key)
        ip_allow_list_data.update({file.name: ip_allow_list[file]})
        # HEAT-223 End : Read and collate data for IPallowlist from all environment specific values.yaml files.

    helm_default_values = get_file_yaml(repo, f"{monorepo_dir_suffix}helm_deploy/{c_name}/values.yaml")
    if helm_default_values:

      ip_allow_list_default = fetch_values_for_allowlist_key(helm_default_values, allow_list_key)

      # Try to get the container image
      try:
        container_image = helm_default_values['image']['repository']
        data.update({"container_image": container_image})
      except KeyError:
        pass
      try:
        container_image = helm_default_values['generic-service']['image']['repository']
        data.update({"container_image": container_image})
      except KeyError:
        pass
      # Try to get the productID
      try:
        product_id = helm_default_values['generic-service']['productId']
        sc_product_id = get_sc_id('products', 'p_id', product_id)
        if sc_product_id:
          data.update({"product": sc_product_id})
      except KeyError:
        pass

  # helm env values files, extract useful values
  helm_envs = {}
  for env in helm_environments:
    values = get_file_yaml(repo, f"{monorepo_dir_suffix}helm_deploy/values-{env}.yaml")
    if values:
      # Ingress hostname
      try:
        host = values['generic-service']['ingress']['host']
        helm_envs.update({env: {'host': host}})
        log.debug(f"{env} ingress host: {host}")
      except KeyError:
        pass
      # Ingress alternative location
      try:
        host = values['generic-service']['ingress']['hosts'][-1]
        helm_envs.update({env: {'host': host}})
        log.debug(f"{env} ingress host: {host}")
      except KeyError:
        pass
      # Ingress alternative location
      try:
        host = values['ingress']['host']
        helm_envs.update({env: {'host': host}})
        log.debug(f"{env} ingress host: {host}")
      except KeyError:
        pass
      # Ingress alternative location
      try:
        host = values['ingress']['hosts'][-1]['host']
        helm_envs.update({env: {'host': host}})
        log.debug(f"{env} ingress host: {host}")
      except KeyError:
        pass
      # Container image alternative location
      try:
        container_image = values['image']['repository']
        data.update({"container_image": container_image})
      except KeyError:
        pass
      try:
        container_image = values['generic-service']['image']['repository']
        data.update({"container_image": container_image})
      except KeyError:
        pass

  environments = []
  if repo.name in bootstrap_projects:
    p = bootstrap_projects[repo.name]
    # Get dev namespace data
    if 'circleci_project_k8s_namespace' in p:
      dev_namespace = p['circleci_project_k8s_namespace']
      e = {'namespace': dev_namespace, 'type': 'dev'}

      ns_id = get_sc_id('namespaces', 'name', dev_namespace)
      if ns_id:
        e.update({'ns': ns_id})

      allow_list_values_for_prj_ns = {}
      if 'dev' in helm_envs:
        dev_url = f"https://{helm_envs['dev']['host']}"
        e.update({'name': 'dev', 'type': 'dev', 'url': dev_url})

        try:
          ip_allow_list_env = ip_allow_list_data['values-dev.yaml']
          allow_list_values_for_prj_ns.update({'values-dev.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
          e.update({'ip_allow_list': allow_list_values_for_prj_ns, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values_for_prj_ns)})
        except KeyError:
          pass

      elif 'development' in helm_envs:
        dev_url = f"https://{helm_envs['development']['host']}"
        e.update({'name': 'development', 'type': 'dev', 'url': dev_url})

        try:
          ip_allow_list_env = ip_allow_list_data['values-development.yaml']
          allow_list_values_for_prj_ns.update({'values-development.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
          e.update({'ip_allow_list': allow_list_values_for_prj_ns, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values_for_prj_ns)})

        except KeyError:
          pass

      else:
        dev_url = False

      if dev_url:
        health_path = "/health"
        info_path = "/info"
        # Hack for hmpps-auth non standard endpoints
        if 'sign-in' in dev_url:
          health_path = "/auth/health"
          info_path = "/auth/info"

        if test_endpoint(dev_url, health_path):
          e.update({'health_path': health_path})
        if test_endpoint(dev_url, info_path):
          e.update({'info_path': info_path})
        if test_swagger_docs(dev_url):
          e.update({'swagger_docs': '/swagger-ui.html'})
          data.update({'api': True, 'frontend': False})
          if test_subject_access_request_endpoint(dev_url):
            e.update({'include_in_subject_access_requests': True})

      # Try to add the existing env ID so we dont overwrite existing env entries
      existing_envs = component["attributes"]["environments"]
      for item in existing_envs:
        if item["name"] == "dev" or item["name"] == "development":
          env_id = item["id"]
          e.update({'id': env_id})
          break
      environments.append(e)

    # Get other env namespaces based on circleci context data
    if 'circleci_context_k8s_namespaces' in p:
      for c in p['circleci_context_k8s_namespaces']:
        e = {}
        allow_list_values = {}
        env_name = c['env_name']
        env_type = c['env_type']

        e.update({'type': env_type, 'name': env_type})

        if env_name in helm_envs:
          env_url = f"https://{helm_envs[env_name]['host']}"
          e.update({'name': env_name, 'url': env_url})
          try:
            ip_allow_list_env = ip_allow_list_data[f'values-{env_name}.yaml']
            allow_list_values.update({f'values-{env_name}.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
            e.update({'ip_allow_list': allow_list_values, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values)})
          except KeyError:
            pass

        elif 'developement' in helm_envs:
          env_url = f"https://{helm_envs['developement']['host']}"
          e.update({'type': 'dev', 'name': 'developement', 'url': env_url})
          try:
            ip_allow_list_env = ip_allow_list_data[f'values-{env_name}.yaml']
            allow_list_values.update({f'values-{env_name}.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
            e.update({'ip_allow_list': allow_list_values, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values)})
          except KeyError:
            pass

        elif 'test' in helm_envs:
          env_url = f"https://{helm_envs['test']['host']}"
          e.update({'type': 'test', 'name': 'test', 'url': env_url})
          try:
            ip_allow_list_env = ip_allow_list_data['values-test.yaml']
            allow_list_values.update({'values-test.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
            e.update({'ip_allow_list': allow_list_values, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values)})
          except KeyError:
            pass

        elif 'testing' in helm_envs:
          env_url = f"https://{helm_envs['testing']['host']}"
          e.update({'type': 'test', 'name': 'testing', 'url': env_url})
          try:
            ip_allow_list_env = ip_allow_list_data['values-testing.yaml']
            allow_list_values.update({'values-testing.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
            e.update({'ip_allow_list': allow_list_values, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values)})
          except KeyError:
            pass

        elif 'staging' in helm_envs:
          env_url = f"https://{helm_envs['staging']['host']}"
          e.update({'type': 'stage', 'name': 'staging', 'url': env_url})
          try:
            ip_allow_list_env = ip_allow_list_data['values-staging.yaml']
            allow_list_values.update({'values-staging.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
            e.update({'ip_allow_list': allow_list_values, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values)})
          except KeyError:
            pass

        elif 'qa' in helm_envs:
          env_url = f"https://{helm_envs['qa']['host']}"
          e.update({'type': 'preprod', 'name': 'qa', 'url': env_url})
          try:
            ip_allow_list_env = ip_allow_list_data['values-qa.yaml']
            allow_list_values.update({'values-qa.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
            e.update({'ip_allow_list': allow_list_values, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values)})
          except KeyError:
            pass
        elif 'production' in helm_envs:
          env_url = f"https://{helm_envs['production']['host']}"
          e.update({'type': 'prod', 'name': 'production', 'url': env_url})
          try:
            ip_allow_list_env = ip_allow_list_data['values-production.yaml']
            allow_list_values.update({'values-production.yaml': ip_allow_list_env, 'values.yaml': ip_allow_list_default})
            e.update({'ip_allow_list': allow_list_values, 'ip_allow_list_enabled': is_ipallowList_enabled(allow_list_values)})
          except KeyError:
            pass

        else:
          env_url = False

        if 'namespace' in c:
          env_namespace = c['namespace']
        else:
          env_namespace = f"{repo.name}-{env_name}"
        e.update({'namespace': env_namespace})
        ns_id = get_sc_id('namespaces', 'name', env_namespace)
        if ns_id:
          e.update({'ns': ns_id})

        if env_url:
          health_path = "/health"
          info_path = "/info"
          # Hack for hmpps-auth non standard endpoints
          if 'sign-in' in env_url:
            health_path = "/auth/health"
            info_path = "/auth/info"

          if test_endpoint(env_url, health_path):
            e.update({'health_path': health_path})
          if test_endpoint(env_url, info_path):
            e.update({'info_path': info_path})
          # Test for API docs - and if found also test for SAR endpoint.
          if test_swagger_docs(env_url):
            e.update({'swagger_docs': '/swagger-ui.html'})
            data.update({'api': True, 'frontend': False})
            if test_subject_access_request_endpoint(env_url):
              e.update({'include_in_subject_access_requests': True})

        # Try to add the existing env ID so we dont overwrite existing env entries
        existing_envs = component["attributes"]["environments"]
        for item in existing_envs:
          if item["name"] == env_name:
            env_id = item["id"]
            e.update({'id': env_id})
            break
        environments.append(e)

  # If no environment data is discovered above, and if environment data has been
  # manually added to the SC, ensure we just pass the existing data to the SC update.
  if not environments:
    environments = component["attributes"]["environments"]

  # App insights cloud_RoleName
  if repo.language == 'Kotlin' or repo.language == 'Java':
    app_insights_config = get_file_json(repo, f"{monorepo_dir_suffix}applicationinsights.json")
    if app_insights_config:
      app_insights_cloud_role_name = app_insights_config['role']['name']
      data.update({"app_insights_cloud_role_name": app_insights_cloud_role_name})

  if repo.language == 'JavaScript' or repo.language == 'TypeScript':
    package_json = get_file_json(repo, f"{monorepo_dir_suffix}package.json")
    if package_json:
      app_insights_cloud_role_name = package_json['name']
      if re.match(r'^[a-zA-Z0-9-_]+$', app_insights_cloud_role_name):
        data.update({"app_insights_cloud_role_name": app_insights_cloud_role_name})

  # Gradle config
  build_gradle_config_content = False
  if repo.language == 'Kotlin' or repo.language == 'Java':
    build_gradle_kts_config = get_file_plain(repo, 'build.gradle.kts')
    build_gradle_config_content = build_gradle_kts_config
  # Try alternative location for java projects
  if not build_gradle_config_content:
    build_gradle_java_config = get_file_plain(repo, 'build.gradle')
    build_gradle_config_content = build_gradle_java_config

  if build_gradle_config_content:
    try:
      regex = 'id\\(\\"uk.gov.justice.hmpps.gradle-spring-boot\\"\\) version \\"(.*)\\"( apply false)?$'
      hmpps_gradle_spring_boot_version = re.search(regex, build_gradle_config_content, re.MULTILINE)[1]
      log.debug(f"Found hmpps gradle-spring-boot version: {hmpps_gradle_spring_boot_version}")
      versions_data.update({'gradle': {'hmpps_gradle_spring_boot': hmpps_gradle_spring_boot_version}})
    except TypeError:
      pass

  # Parse Dockerfile
  try:
    file_contents = repo.get_contents(f"{monorepo_dir_suffix}Dockerfile")
    dockerfile = DockerfileParser(fileobj=tempfile.NamedTemporaryFile())
    dockerfile.content = b64decode(file_contents.content)
    # Get list of parent images, and strip out references to 'base'
    parent_images = list(filter(lambda i: i != 'base', dockerfile.parent_images))
    # Get the last element in the array, which should be the base image of the final stage.
    base_image = parent_images[-1]
    versions_data.update({'dockerfile': {'base_image': base_image}})
    log.debug(f"Found Dockerfile base image: {base_image}")
  except github.UnknownObjectException:
    log.info(f"404 File not found {repo.name}:Dockerfile")
  except Exception as e:
    log.error(f"Error parsing Dockerfile: {e}")

  # Add Environments to final data dict
  data.update({"environments": environments})

  # Add versions to final data dict.
  data.update({'versions': versions_data}) 

  # Update component with all results in data dict.
  update_sc_component(c_id, data)


def startHttpServer():
  handler_object = HealthHttpRequestHandler
  with socketserver.TCPServer(("", 8080), handler_object) as httpd:
    httpd.serve_forever()


def process_components(data):
  log.info(f"Processing batch of {len(data)} components...")
  for component in data:
    # Wait until the API limit is reset if we are close to the limit
    while core_rate_limit.remaining < 100:
      time_delta = datetime.now() - core_rate_limit.reset
      time_to_reset = time_delta.total_seconds()
      log.info(f"Github API rate limit {core_rate_limit}")
      log.info(f"Backing off for {time_to_reset} second, to avoid github API limits.")
      sleep(time_to_reset)

    t_repo = threading.Thread(target=process_repo, kwargs=component, daemon=True)

    # Apply limit on total active threads, avoid github secondary API rate limit
    while threading.active_count() > (MAX_THREADS-1):
      log.debug(f"Active Threads={threading.active_count()}, Max Threads={MAX_THREADS}")
      sleep(10)

    t_repo.start()
    component_name = component["attributes"]["name"]
    log.info(f"Started thread for {component_name}")


if __name__ == '__main__':
  logging.basicConfig(
      format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=LOG_LEVEL)
  log = logging.getLogger(__name__)

  sc_api_headers = {"Authorization": f"Bearer {SC_API_TOKEN}", "Content-Type": "application/json", "Accept": "application/json"}

  # Test connection to Service Catalogue
  try:
    r = requests.head(f"{SC_API_ENDPOINT}/_health", headers=sc_api_headers, timeout=10)
    log.info(f"Successfully connected to the Service Catalogue. {r.status_code}")
  except Exception as e:
    log.critical("Unable to connect to the Service Catalogue.")
    raise SystemExit(e) from e

  # Test auth and connection to github
  try:
    private_key = b64decode(GITHUB_APP_PRIVATE_KEY).decode('ascii')
    auth = github.Auth.AppAuth(GITHUB_APP_ID, private_key).get_installation_auth(GITHUB_APP_INSTALLATION_ID)
    gh = github.Github(auth=auth, pool_size=50)

    rate_limit = gh.get_rate_limit()
    core_rate_limit = rate_limit.core
    log.info(f"Github API: {rate_limit}")
    # test fetching organisation name
    gh.get_organization("ministryofjustice")
  except Exception as e:
    log.critical("Unable to connect to the github API.")
    raise SystemExit(e) from e

  while True:
    # Start health endpoint.
    httpHealth = threading.Thread(target=startHttpServer, daemon=True)
    httpHealth.start()

    # Get projects.json from bootstrap repo for namespaces data
    bootstrap_repo = gh.get_repo("ministryofjustice/hmpps-project-bootstrap")
    bootstrap_projects_json = get_file_json(bootstrap_repo, 'projects.json')
    # Convert dict for easier lookup
    bootstrap_projects = {}
    for p in bootstrap_projects_json:
      bootstrap_projects.update({p['github_repo_name']: p})

    log.info(SC_ENDPOINT)
    try:
      r = requests.get(SC_ENDPOINT, headers=sc_api_headers, timeout=10)
      log.debug(r)
      if r.status_code == 200:
        j_meta = r.json()["meta"]["pagination"]
        log.debug(f"Got result page: {j_meta['page']} from SC")
        j_data = r.json()["data"]
        process_components(j_data)
      else:
        raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")

      # Loop over the remaining pages and return one at a time
      num_pages = j_meta['pageCount']
      for p in range(2, num_pages+1):
        page = f"&pagination[page]={p}"
        r = requests.get(f"{SC_ENDPOINT}{page}", headers=sc_api_headers, timeout=10)
        if r.status_code == 200:
          j_meta = r.json()["meta"]["pagination"]
          log.debug(f"Got result page: {j_meta['page']} from SC")
          j_data = r.json()["data"]
          process_components(j_data)
        else:
          raise Exception(f"Received non-200 response from Service Catalogue: {r.status_code}")

    except Exception as e:
      log.error(f"Problem with Service Catalogue API. {e}")

    sleep((REFRESH_INTERVAL_HOURS * 60 * 60))

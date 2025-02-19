import requests
import yaml
import json
import logging


class AlertmanagerData:
  def __init__(self, am_params, log_level=logging.INFO):
    # Needs custom logging because of a bit of a mess later on
    logging.basicConfig(
      format='[%(asctime)s] %(levelname)s %(threadName)s %(message)s', level=log_level
    )
    self.log = logging.getLogger(__name__)
    self.url = am_params['url']
    self.get_alertmanager_data()

  def get_alertmanager_data(self):
    self.json_config_data = None
    try:
      response = requests.get(self.url, verify=False, timeout=5)
      if response.status_code == 200:
        alertmanager_data = response.json()
        config_data = alertmanager_data['config']
        formatted_config_data = config_data['original'].replace('\\n', '\n')
        yaml_config_data = yaml.safe_load(formatted_config_data)
        self.json_config_data = json.loads(json.dumps(yaml_config_data))
        self.log.info('Successfully fetched Alertmanager data')
      else:
        self.log.error(f'Error: {response.status_code}')

    except requests.exceptions.SSLError as e:
      self.log.error(f'SSL Error: {e}')

    except requests.exceptions.RequestException as e:
      self.log.error(f'Request Error: {e}')

    except json.JSONDecodeError as e:
      self.log.error(f'JSON Decode Error: {e}')

    except Exception as e:
      self.log.error(f'Error getting data from Alertmanager: {e}')

  def find_channel_by_severity_label(self, alert_severity_label):
    # Find the receiver name for the given severity
    receiver_name = ''
    if self.json_config_data is None:
      return ''

    for route in self.json_config_data['route']['routes']:
      if route['match'].get('severity') == alert_severity_label:
        receiver_name = route['receiver']
        break
    # Find the channel for the receiver name
    if receiver_name:
      for receiver in self.json_config_data['receivers']:
        if receiver['name'] == receiver_name:
          slack_configs = receiver.get('slack_configs', [])
          if slack_configs:
            return slack_configs[0].get('channel')
          else:
            return ''

  ################################################################################################
  # get_existing_alertmanager_config
  # This function will get the existing alertmanager config from the component
  # to prevent it being overwritten by blank entries in case the data is not
  # available due to missing alertmanager data
  def get_existing_alertmanager_config(self, component, env_name, services):
    am_data = {}
    log = services.log
    if envs := component['attributes'].get('environments'):
      env_data = next(
        (env for env in envs if env.get('name') == env_name),
        {},
      )
      alert_severity_label = env_data.get('alert_severity_label')
      alerts_slack_channel = env_data.get('alerts_slack_channel')
      log.debug(
        f'Existing alertmanager config: {alert_severity_label}, {alerts_slack_channel}'
      )
      am_data = {
        'alert_severity_label': alert_severity_label,
        'alerts_slack_channel': alerts_slack_channel,
      }

    return am_data

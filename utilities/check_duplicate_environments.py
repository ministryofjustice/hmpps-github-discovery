#!/usr/bin/env python
"""Check for duplicate environments

Required environment variables
------------------------------

Service Catalogue
- SERVICE_CATALOGUE_API_ENDPOINT: Service Catalogue API endpoint
- SERVICE_CATALOGUE_API_KEY: Service Catalogue API key
- SLACK_ALERTS_CHANNEL: Slack channel
"""

import os
import json
import sys
from hmpps import ServiceCatalogue


def eprint(*args, **kwargs):
  print(*args, file=sys.stderr, **kwargs)


def main():
  # service catalogue parameters

  sc = ServiceCatalogue()

  channel_id = os.getenv('SLACK_ALERTS_CHANNEL')

  sc_link_stub = (
    f'{sc.url}/admin/content-manager/collection-types/'
    f'api::environment.environment?sort=component.name:DESC'
  )

  message = ''
  slack_template = {
    'channel': f'{channel_id}',
    'text': ':warning: Duplicate environments found in Service Catalogue\n'
    'Please check and remedy as soon as possible.',
    'blocks': [
      {
        'type': 'section',
        'text': {
          'type': 'mrkdwn',
          'text': ':warning: Duplicate environments found in Service Catalogue\n'
          'Please check and remedy as soon as possible.',
        },
      },
      {
        'type': 'section',
        'text': {
          'type': 'mrkdwn',
          'text': '',
        },
      },
    ],
  }

  # environments bits
  environments = sc.get_all_records('environments?populate=component')
  env_dict = {}
  for env in environments:
    #   attrs = env.get('attributes', {})
    env_name = env.get('name')
    component_name = (env.get('component') or {}).get('name')
    if env_name in env_dict:
      if component_name in env_dict.get(env_name):
        env_dict[env_name][component_name] += 1
      else:
        env_dict[env_name][component_name] = 1
    else:
      env_dict[env_name] = {component_name: 1}

  for env, component in env_dict.items():
    for component_name, qty in component.items():
      if qty > 1:
        if component_name:
          sc_component_filter = (
            f'&filters[$and][0][component][name][$eq]={component_name}'
          )
        else:
          sc_component_filter = '&filters[$and][0][component][name][$null]=true'
        if env:
          sc_env_filter = f'&filters[$and][1][name][$eq]={env}'
        else:
          sc_env_filter = '&filters[$and][1][name][$null]=true'
        link_url = f'{sc_link_stub}{sc_component_filter}{sc_env_filter}'
        if not message:
          message += '*Environments*:\n===========\n'
        message += f'- <{link_url}|{env} - {component_name}> has {qty} entries\n'

        # Construct the message
        if message:
          slack_template['blocks'][1]['text']['text'] = message
          with open('slack-message.json', 'w') as f:
            json.dump(slack_template, f)
          f.close()
          value = 'YES'
        else:
          value = 'NO'

        gh_out = os.environ.get('GITHUB_OUTPUT')
        if gh_out:
          with open(gh_out, 'a') as fh:
            fh.write(f'results={value}\n')
          eprint(f'Wrote to $GITHUB_OUTPUT: results={value}')
        else:
          eprint('GITHUB_OUTPUT env var not found')


if __name__ == '__main__':
  main()

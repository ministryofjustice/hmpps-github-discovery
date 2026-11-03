from includes.utils import (
  get_slack_channel_name_if_id,
  is_ipallowList_enabled,
)


class SlackStub:
  def __init__(self):
    self.looked_up_ids = []

  def get_slack_channel_name_by_id(self, channel_id):
    self.looked_up_ids.append(channel_id)
    return 'resolved-channel'


def test_slack_channel_id_is_resolved():
  slack = SlackStub()

  assert get_slack_channel_name_if_id(slack, 'C0123456789') == 'resolved-channel'
  assert slack.looked_up_ids == ['C0123456789']


def test_slack_channel_name_is_not_looked_up():
  slack = SlackStub()

  assert get_slack_channel_name_if_id(slack, '#team-alerts') is None
  assert get_slack_channel_name_if_id(slack, None) is None
  assert slack.looked_up_ids == []


def test_ip_allow_list_disabled_when_false():
	data = {
		'values-dev.yaml': {'allowlist': False},
		'values.yaml': {},
	}

	assert is_ipallowList_enabled(data) is False


def test_ip_allow_list_enabled_with_nested_groups_and_cidrs():
	data = {
		'values-dev.yaml': {
			'groups': [
				'internal',
				'prisons',
			],
			'test-1': '1.1.1.1/32',
			'test-2': '2.2.2.2/32',
			'test-3': '3.3.3.3/32',
		},
		'values.yaml': {},
	}

	assert is_ipallowList_enabled(data) is True


def test_ip_allow_list_disabled_when_true():
	data = {
		'values-dev.yaml': {'allowlist': True},
		'values.yaml': {},
	}

	assert is_ipallowList_enabled(data) is False


def test_ip_allow_list_disabled_when_empty_or_null():
	data = {
		'values-dev.yaml': {'allowlist': None},
		'values.yaml': {},
	}

	assert is_ipallowList_enabled(data) is False

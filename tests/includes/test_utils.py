from includes.utils import (
  get_slack_channel_name_and_id,
  is_ipallowList_enabled,
)


class SlackStub:
  def __init__(self):
    self.looked_up_ids = []

  def get_slack_channel_counterpart(self, channel):
    self.looked_up_ids.append(channel)
    if channel == 'C0123456789':
      return 'resolved-channel'
    if channel in ('#team-alerts', 'team-alerts'):
      return 'C0123456789'
    return None


def test_slack_channel_name_and_id_are_resolved_from_id():
  slack = SlackStub()

  assert (
    get_slack_channel_name_and_id(slack, 'C0123456789')
    == 'resolved-channel|C0123456789'
  )


def test_slack_channel_name_and_id_are_resolved_from_name():
  slack = SlackStub()

  assert (
    get_slack_channel_name_and_id(slack, '#team-alerts')
    == 'team-alerts|C0123456789'
  )


def test_slack_channel_name_and_id_returns_none_when_unresolved():
  slack = SlackStub()

  assert get_slack_channel_name_and_id(slack, 'missing-channel') == (
    'missing-channel|none'
  )


def test_slack_channel_name_and_id_uses_none_for_unresolved_channel_id():
  slack = SlackStub()

  assert (
    get_slack_channel_name_and_id(slack, 'C9999999999')
    == 'none|C9999999999'
  )


def test_slack_channel_name_and_id_returns_none_values_for_empty_channel():
  slack = SlackStub()

  assert get_slack_channel_name_and_id(slack, '') == 'none|none'


def test_slack_channel_name_and_id_strips_surrounding_whitespace():
  slack = SlackStub()

  assert (
    get_slack_channel_name_and_id(slack, ' C0123456789\t')
    == 'resolved-channel|C0123456789'
  )
  assert slack.looked_up_ids == ['C0123456789']


def test_slack_channel_name_and_id_treats_whitespace_only_as_empty():
  slack = SlackStub()

  assert get_slack_channel_name_and_id(slack, ' \t') == 'none|none'
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

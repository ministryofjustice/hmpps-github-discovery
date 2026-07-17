from includes.utils import is_ipallowList_enabled


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

from harness_mem.autonomous.executors.codex_app_server import CodexAppServer
from harness_mem.autonomous.provider import ProviderError
import pytest


def test_native_mcp_merge_retains_private_fields_without_weakening_disabled_flags():
    owner = CodexAppServer('unused', scope_factory=None, remove_directory=None, poll_seconds=0.2)
    config = {'mcp_servers': {'a': {'enabled': False, 'env': {'TOKEN': 'fictional'}},
                              'inherited': {'enabled': False}}}
    assert owner._attest(config, {'mcp_servers': {'a': {'enabled': False}}}) == ['a', 'inherited']
    config['mcp_servers']['inherited']['enabled'] = True
    with pytest.raises(ProviderError, match='MCP isolation unattested'):
        owner._attest(config, {'mcp_servers': {'a': {'enabled': False}}})


@pytest.mark.parametrize('higher, expected', [(False, False), (True, True)])
def test_native_omitted_tool_field_uses_highest_enabled_layer(higher, expected):
    def layer(value, **extra):
        return {'config': {'tools': {'experimental_request_user_input': {'enabled': value}}}, **extra}
    response = {'config': {'tools': {'web_search': None}},
                'layers': [layer(not higher, disabledReason='ignored'), layer(higher), layer(not higher)]}
    result = CodexAppServer._attestation_config(response)
    assert result['tools.experimental_request_user_input.enabled'] is expected
    assert response['config'] == {'tools': {'web_search': None}}
    assert not any('TOKEN' in key for key in result)


def test_native_absent_tool_boolean_remains_unattested_not_false():
    result = CodexAppServer._attestation_config({'config': {'tools': {}}, 'layers': []})
    owner = CodexAppServer('unused', scope_factory=None, remove_directory=None, poll_seconds=0.2)
    with pytest.raises(ProviderError, match='override unattested'):
        owner._attest(result, {'tools.experimental_request_user_input.enabled': False})

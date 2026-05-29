import sys
import types
import unittest
from unittest import mock

agent_mod = types.ModuleType('agent')
class Agent:  # pragma: no cover
    pass
agent_mod.Agent = Agent
sys.modules.setdefault('agent', agent_mod)

helpers_mod = types.ModuleType('helpers')
plugins_mod = types.ModuleType('helpers.plugins')
plugins_mod.get_plugin_config = lambda *args, **kwargs: {}
helpers_mod.plugins = plugins_mod
sys.modules.setdefault('helpers', helpers_mod)
sys.modules.setdefault('helpers.plugins', plugins_mod)

import config
from tools.shared import resolve_notebook_id


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class DummyClient:
    def __init__(self, notebooks):
        self.notebooks = notebooks
    async def get(self, url, params=None):
        return DummyResponse(self.notebooks)


async def _dummy_get_client(client):
    return client


class DummyAgent:
    pass


class OpenNotebookFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import client
        self.client = client
        self._orig_get_api_url = config.get_api_url
        self._orig_get_client = client.get_client

    async def asyncTearDown(self):
        config.get_api_url = self._orig_get_api_url
        self.client.get_client = self._orig_get_client

    async def test_resolve_notebook_id_by_name(self):
        config.get_api_url = lambda agent: 'http://example'
        self.client.get_client = lambda: _dummy_get_client(DummyClient([
            {'id': 'notebook:abc123', 'name': '🕵🏾‍♂️ Agent Zero'}
        ]))
        result = await resolve_notebook_id(DummyAgent(), 'Agent Zero')
        self.assertEqual(result, 'notebook:abc123')

    async def test_resolve_notebook_id_by_full_id(self):
        result = await resolve_notebook_id(DummyAgent(), 'notebook:abc123')
        self.assertEqual(result, 'notebook:abc123')

    async def test_resolve_notebook_id_by_short_suffix(self):
        config.get_api_url = lambda agent: 'http://example'
        self.client.get_client = lambda: _dummy_get_client(DummyClient([
            {'id': 'notebook:xyz789', 'name': 'Other'}
        ]))
        result = await resolve_notebook_id(DummyAgent(), 'xyz789')
        self.assertEqual(result, 'notebook:xyz789')

    async def test_config_prefers_env_then_localhost(self):
        import os
        old = os.environ.get('OPEN_NOTEBOOK_API_URL')
        try:
            os.environ['OPEN_NOTEBOOK_API_URL'] = 'http://env.example:5055'
            self.assertEqual(config.get_api_url(DummyAgent()), 'http://env.example:5055')
            del os.environ['OPEN_NOTEBOOK_API_URL']
            config._get_config = lambda agent: {}
            self.assertEqual(config.get_api_url(DummyAgent()), 'http://localhost:5055')
        finally:
            if old is None:
                os.environ.pop('OPEN_NOTEBOOK_API_URL', None)
            else:
                os.environ['OPEN_NOTEBOOK_API_URL'] = old


if __name__ == '__main__':
    unittest.main()

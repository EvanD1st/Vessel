import httpx
import pytest

from vessel.orbio import (
    InvalidOrbioCredential,
    OrbioGatewayClient,
    OrbioManagementUnavailable,
    OrbioRemoteMCPClient,
    RealOrbioAdapter,
    mask_key,
)


def test_mask_key():
    assert mask_key('sk-orbio-1234567890abcdef') == 'sk-orbio-••••cdef'
    assert mask_key('sk-testkey123456') == 'sk-••••3456'
    assert mask_key('plainapikey12345') == 'pla••••2345'
    assert mask_key('short') == '••••••••'


@pytest.mark.asyncio
async def test_gateway_validation_success():
    def handler(request: httpx.Request):
        assert request.headers['authorization'] == 'Bearer sk-orbio-valid-key-1234'
        return httpx.Response(
            200,
            json={
                'model': 'openai/gpt-4.1-mini',
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'READY'}}],
            },
        )

    transport = httpx.MockTransport(handler)
    client = OrbioGatewayClient(transport=transport)
    result = await client.validate('sk-orbio-valid-key-1234')
    assert result['valid'] is True
    assert result['masked_key'] == 'sk-orbio-••••1234'


@pytest.mark.asyncio
async def test_gateway_validation_unauthorized():
    def handler(request: httpx.Request):
        return httpx.Response(401, json={'error': {'message': 'Invalid API key'}})

    transport = httpx.MockTransport(handler)
    client = OrbioGatewayClient(transport=transport)
    with pytest.raises(InvalidOrbioCredential) as exc_info:
        await client.validate('sk-orbio-bad-key-1234')
    assert 'Invalid API key' not in str(exc_info.value)
    assert 'unauthorized' in str(exc_info.value)


@pytest.mark.asyncio
async def test_gateway_validation_malformed_response():
    def handler(request: httpx.Request):
        return httpx.Response(200, json={'model': 'openai/gpt-4.1-mini', 'choices': []})

    transport = httpx.MockTransport(handler)
    client = OrbioGatewayClient(transport=transport)
    with pytest.raises(InvalidOrbioCredential):
        await client.validate('sk-orbio-bad-key-1234')


@pytest.mark.asyncio
async def test_mcp_unconfigured_fails_closed():
    client = OrbioRemoteMCPClient()
    assert client.is_configured is False
    balance = await client.get_balance()
    assert balance['available'] is False
    assert balance['currency'] == 'CREDIT'
    assert 'Remote MCP' in balance['reason']

    key_status = await client.get_key_status()
    assert key_status['available'] is False

    with pytest.raises(OrbioManagementUnavailable):
        await client.create_key('test-key')

    with pytest.raises(OrbioManagementUnavailable):
        await client.revoke_key('key-1')


@pytest.mark.asyncio
async def test_mcp_configured_calls_tool():
    def handler(request: httpx.Request):
        assert request.headers['authorization'] == 'Bearer mcp-secret-token'
        return httpx.Response(
            200,
            json={'jsonrpc': '2.0', 'id': 1, 'result': {'balance': 42.50, 'currency': 'CREDIT'}},
        )

    transport = httpx.MockTransport(handler)
    client = OrbioRemoteMCPClient(
        mcp_endpoint='https://mcp.orbio.example/rpc',
        mcp_auth_token='mcp-secret-token',
        transport=transport,
    )
    assert client.is_configured is True
    balance = await client.get_balance()
    assert balance['available'] is True
    assert balance['amount'] == 42.50
    assert balance['currency'] == 'CREDIT'


@pytest.mark.asyncio
async def test_real_orbio_adapter_caching_and_status():
    clock_time = [1000.0]
    adapter = RealOrbioAdapter(clock=lambda: clock_time[0])
    assert adapter.capabilities.credential_validation is True
    assert adapter.capabilities.balance_read is False

    status = await adapter.connection_status()
    assert status['gateway']['status'] == 'unconfigured'
    assert status['balance']['available'] is False

    status2 = await adapter.connection_status()
    assert status2 is status


def test_orbio_cli_lifecycle(tmp_path, monkeypatch, capsys):
    from vessel import cli
    from vessel.service import Vessel

    v = Vessel(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    v.enroll(str(workspace), "test mission")
    v.close()

    # Mock validate_credential so network calls don't fail offline
    async def fake_validate(self, key):
        if not key.startswith("sk-orbio-valid"):
            from vessel.orbio import InvalidOrbioCredential

            raise InvalidOrbioCredential("Invalid key")
        return {"status": "valid", "masked_key": "sk-orbio-••••" + key[-4:]}

    monkeypatch.setattr(
        "vessel.orbio.RealOrbioAdapter.validate_credential",
        fake_validate,
    )

    # Status before configuration
    assert cli.main(["--state", str(tmp_path), "orbio", "status"]) == 0
    out = capsys.readouterr().out
    assert '"connected": false' in out
    assert '"probe_status": "unconfigured"' in out

    # Set invalid key fails
    assert cli.main(["--state", str(tmp_path), "orbio", "set-key", "--key", "sk-invalid"]) == 1

    # Set valid key succeeds
    assert cli.main(["--state", str(tmp_path), "orbio", "set-key", "--key", "sk-orbio-valid-1234"]) == 0
    out = capsys.readouterr().out
    assert '"status": "active"' in out
    assert '"masked_key": "sk-orbio-••••1234"' in out

    # Status reflects active key
    assert cli.main(["--state", str(tmp_path), "orbio", "status"]) == 0
    out = capsys.readouterr().out
    assert '"connected": true' in out
    assert '"masked_key": "sk-orbio-••••1234"' in out

    # Replace key
    assert cli.main(["--state", str(tmp_path), "orbio", "replace-key", "--key", "sk-orbio-valid-5678"]) == 0
    out = capsys.readouterr().out
    assert '"credential_version": "v2"' in out
    assert '"masked_key": "sk-orbio-••••5678"' in out

    # Forget key
    assert cli.main(["--state", str(tmp_path), "orbio", "forget-key"]) == 0
    out = capsys.readouterr().out
    assert '"status": "removed"' in out
    assert '"recovery_history_preserved": true' in out

    # Final status is unconfigured again
    assert cli.main(["--state", str(tmp_path), "orbio", "status"]) == 0
    out = capsys.readouterr().out
    assert '"connected": false' in out


@pytest.mark.asyncio
async def test_claim_key_mcp_unconfigured():
    adapter = RealOrbioAdapter()
    res = await adapter.claim_key("test-op")
    assert res["success"] is False
    assert res["status"] == "mcp_not_configured"
    assert "https://orbio.so" in res["url"]


@pytest.mark.asyncio
async def test_claim_key_mcp_configured():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"key": "sk-or-v1-claimed-secret-key-12345678", "name": "my-key"},
            },
        )

    transport = httpx.MockTransport(handler)
    mcp_client = OrbioRemoteMCPClient(
        mcp_endpoint="https://mcp.orbio.example/rpc",
        mcp_auth_token="token",
        transport=transport,
    )
    adapter = RealOrbioAdapter(mcp_client=mcp_client)
    res = await adapter.claim_key("my-key")
    assert res["success"] is True
    assert res["status"] == "claimed"
    assert res["masked_key"] == "sk-••••5678"


@pytest.mark.asyncio
async def test_fetch_model_catalog_fallback():
    adapter = RealOrbioAdapter()
    catalog = await adapter.fetch_model_catalog()
    assert len(catalog) >= 8
    model_ids = [m["id"] for m in catalog]
    assert "openrouter/auto" in model_ids
    assert "anthropic/claude-sonnet-4.5" in model_ids
    assert "deepseek/deepseek-r1" in model_ids
    auto_model = next(m for m in catalog if m["id"] == "openrouter/auto")
    assert auto_model["recommended"] is True


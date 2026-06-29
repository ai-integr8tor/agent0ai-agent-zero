from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WHATS_NEW_PLUGIN = PROJECT_ROOT / "plugins/_whats_new"


def test_whats_new_modal_uses_showcase_assets_and_branded_footer():
    html = (WHATS_NEW_PLUGIN / "webui/main.html").read_text(encoding="utf-8")
    store = (WHATS_NEW_PLUGIN / "webui/whats-new-store.js").read_text(encoding="utf-8")

    assert "What's New in Agent Zero" in html
    assert "data-modal-footer" in html
    assert "btn btn-ok" in html
    assert "btn btn-field" in html
    assert "type=\"checkbox\"" in html
    assert "Don't show automatically again" in html
    assert "/plugins/_whats_new/webui/whats-new-store.js" in html
    assert "/plugins/_whats_new/webui/assets" in store
    assert "a0_whats_new_never_show" in store

    for asset in ["parallel-subs.webm", "mcp-servers.png", "skills-scanner.png"]:
        assert asset in html + store
        assert (PROJECT_ROOT / "plugins/_whats_new/webui/assets" / asset).exists()

    assert "Parallel tool calls and subagents" in store
    assert (
        "Agent Zero can now split work across parallel tool and subagents calls and combine concurrent steps results."
        in store
    )
    assert "Redesigned MCP configuration UI" in store
    assert "Skills Scanner powered by Snyk Agent Scan" in store
    assert "Remote URL transports" in store
    assert "Raw JSON" in store
    assert "prompt-injection risks" in store
    assert "Catch risky skill instructions early" in store
    assert "Include MCP servers in the same pass" not in store


def test_whats_new_legacy_modal_path_redirects_to_main_screen():
    html = (WHATS_NEW_PLUGIN / "webui/whats-new.html").read_text(encoding="utf-8")

    assert "/plugins/_whats_new/webui/main.html" in html
    assert "openModal(mainPath)" in html
    assert "What's New in Agent Zero" in html


def test_whats_new_startup_trigger_is_version_gated_with_opt_out():
    content = (
        WHATS_NEW_PLUGIN / "extensions/webui/initFw_end/whats-new.js"
    ).read_text(encoding="utf-8")

    assert "globalThis.gitinfo?.version" in content
    assert "a0_whats_new_seen_version" in content
    assert "a0_whats_new_never_show" in content
    assert "/plugins/_whats_new/webui/main.html" in content
    assert "/plugins/_whats_new/webui/whats-new.html" in content
    assert "compareVersions" in content
    assert "storedSeenVersion" in content
    assert "shouldShowWhatsNew" in content
    assert "shouldNeverShow" in content
    assert "modal-closed" in content
    assert "markVersionSeen" in content


def test_whats_new_exposes_builtin_plugin_open_screen():
    assert (WHATS_NEW_PLUGIN / "webui/main.html").exists()


def test_whats_new_plugin_manifest_is_always_enabled():
    manifest = (WHATS_NEW_PLUGIN / "plugin.yaml").read_text(encoding="utf-8")

    assert "name: _whats_new" in manifest
    assert "always_enabled: true" in manifest
    assert "settings_sections: []" in manifest

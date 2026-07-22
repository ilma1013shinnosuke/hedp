import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTH_SOURCE = ROOT / "cloud" / "gas" / "fusionsolar" / "AuthHealth.gs"


def run_auth_health_scenario(recipient: bool) -> dict:
    source = AUTH_SOURCE.read_text()
    setup = "values.SUMICORE_AUTH_ALERT_EMAIL = 'alert@example.invalid';" if recipient else ""
    script = f"""
const vm = require('vm');
const values = {{}};
const sent = [];
const context = {{
  Error, Date, isNaN,
  PropertiesService: {{ getScriptProperties: () => ({{
    getProperty: key => values[key] || null,
    setProperty: (key, value) => {{ values[key] = String(value); }},
    setProperties: entries => Object.assign(values, entries)
  }}) }},
  MailApp: {{ sendEmail: message => sent.push(message) }}
}};
vm.createContext(context);
vm.runInContext({json.dumps(source)}, context);
{setup}
const first = context.reportFusionSolarAuthenticationExpired_('http_401', new Date('2026-07-22T01:00:00Z'));
const second = context.reportFusionSolarAuthenticationExpired_('redirect', new Date('2026-07-22T02:00:00Z'));
const healthy = context.reportFusionSolarAuthenticationHealthy_(new Date('2026-07-22T03:00:00Z'));
process.stdout.write(JSON.stringify({{
  reasons: [
    context.fusionSolarAuthenticationFailureReason_(401, 'application/json'),
    context.fusionSolarAuthenticationFailureReason_(302, ''),
    context.fusionSolarAuthenticationFailureReason_(200, 'text/html'),
    context.fusionSolarAuthenticationFailureReason_(500, 'text/html'),
    context.fusionSolarAuthenticationFailureReason_(200, 'application/json')
  ], first, second, healthy, sent, values
}}));
"""
    completed = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def test_auth_failure_classification_and_notification_cooldown() -> None:
    result = run_auth_health_scenario(recipient=True)
    assert result["reasons"] == ["http_401", "redirect", "html_response", "", ""]
    assert result["first"]["notification"] == "sent"
    assert result["second"]["notification"] == "cooldown"
    assert len(result["sent"]) == 1
    assert "CookieとCSRF" in result["sent"][0]["body"]
    assert "alert@example.invalid" not in result["sent"][0]["body"]
    assert result["values"]["SUMICORE_FUSIONSOLAR_AUTH_LAST_REASON"] == "redirect"
    assert result["healthy"] == {"status": "healthy", "recovered": True}
    assert result["values"]["SUMICORE_FUSIONSOLAR_AUTH_STATUS"] == "healthy"
    assert result["values"]["SUMICORE_FUSIONSOLAR_AUTH_NOTIFICATION_STATE"] == "recovered"


def test_auth_failure_without_recipient_is_still_recorded() -> None:
    result = run_auth_health_scenario(recipient=False)
    assert result["first"]["notification"] == "recipient_not_configured"
    assert result["second"]["notification"] == "recipient_not_configured"
    assert result["sent"] == []
    assert result["values"]["SUMICORE_FUSIONSOLAR_AUTH_STATUS"] == "healthy"

"""
Session Guard - Prevents container lockups by protecting session 0 from long-running processes.

Intercepts code_execution_tool calls via tool_execute_before extension point.
Analyzes command risk and either warns, redirects to higher session, or blocks execution.

Risk Scoring:
    - Safe patterns (ls, cat, grep, ps, curl, etc.) → allow in session 0
    - High-risk patterns (kg_pipeline, distill, bulk, while True, sleep 300+) → high risk
    - Code length > threshold → risk factor
    - Line count > threshold → risk factor
    - Contains subprocess/async patterns → risk factor

Enforcement Modes:
    - warn: Log warning but allow execution (tuning phase)
    - redirect: Auto-redirect to next available session
    - block: Prevent execution entirely

Architecture:
    tool_execute_before -> intercept code_execution_tool -> analyze risk ->
    [allow | warn | redirect session | block]
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback
from datetime import datetime
from typing import Any

import yaml

from helpers.extension import Extension
from helpers.print_style import PrintStyle


class SessionGuard(Extension):
    """Intercepts code_execution_tool calls and protects session 0."""


    def __init__(self, agent=None, **kwargs):
        super().__init__(agent=agent, **kwargs)
        self._cb_failures = 0
        self._cb_fallback_until = 0  # unix timestamp; 0 = active
    # ── Configuration ───────────────────────────────────────────────

    def _get_config(self) -> dict:
        """Load plugin config from default_config.yaml."""
        try:
            # Navigate from extension file to plugin root:
            # extensions/python/tool_execute_before/_10_session_guard.py
            # -> _session_guard/plugin.yaml
            plugin_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            )
            config_path = os.path.join(plugin_dir, 'default_config.yaml')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            if self.agent:
                PrintStyle.warning(f"Session Guard: Failed to load config: {e}")
        return {
            'enabled': True,
            'enforcement_mode': 'warn',
            'max_session0_code_length': 5000,
            'max_session0_lines': 6,
            'session0_max_runtime_seconds': 60,
            'high_risk_patterns': [],
            'safe_patterns': [],
            'redirect_session': 'auto',
            'log_file': '/a0/usr/workdir/logs/session_guard.log',
            'log_level': 'info',
            'stats_enabled': True,
            'stats_file': '/a0/usr/workdir/logs/session_guard_stats.json',
        }

    # ── Risk Analysis ────────────────────────────────────────────────

    def _calculate_risk_score(
        self, tool_args: dict[str, Any], config: dict
    ) -> tuple[int, list[str], str]:
        """
        Calculate risk score for a code_execution_tool call.

        Returns:
            (risk_score: 0-100, matched_patterns: list, risk_category: str)
        """
        code = tool_args.get('code', '')
        runtime = tool_args.get('runtime', '')
        session = tool_args.get('session', 0)

        # Not session 0 - no risk
        if session != 0 and runtime != 'output':
            # 'output' runtime can happen on any session - check if original was 0
            if session != 0:
                return 0, [], 'low'

        score = 0
        reasons = []

        # Check against safe patterns first (short-circuit for safe commands)
        safe_patterns = config.get('safe_patterns', [])
        for pattern in safe_patterns:
            try:
                if re.search(pattern, code, re.IGNORECASE):
                    # Safe command - reset risk but still check length
                    if len(code) < 200 and code.count('\n') < 3:
                        return 0, [], 'safe'
            except re.error:
                continue

        # Check code length risk
        max_len = config.get('max_session0_code_length', 5000)
        if len(code) > max_len:
            score += 40
            reasons.append(f'code_length>{max_len}')
        elif len(code) > max_len // 2:
            score += 20
            reasons.append(f'code_length>{max_len//2}')

        # Check line count risk
        lines = code.count('\n') + 1
        max_lines = config.get('max_session0_lines', 6)
        if lines > max_lines * 3:
            score += 30
            reasons.append(f'lines>{max_lines*3}')
        elif lines > max_lines:
            score += 15
            reasons.append(f'lines>{max_lines}')

        # Check high-risk patterns
        high_risk_patterns = config.get('high_risk_patterns', [])
        for pattern in high_risk_patterns:
            try:
                if re.search(pattern, code, re.IGNORECASE):
                    score += 25
                    reasons.append(f'high_risk:"{pattern[:30]}"')
            except re.error:
                continue

        # Additional heuristics for Python code
        if runtime in ('python', 'nodejs'):
            # Infinite loops
            if re.search(r'while[\s]*True', code, re.IGNORECASE):
                score += 50
                reasons.append('infinite_loop')
            # Long sleep
            sleep_match = re.search(r'sleep[\s]*\([\s]*(\d+)[\s]*\)', code, re.IGNORECASE)
            if sleep_match:
                sleep_seconds = int(sleep_match.group(1))
                if sleep_seconds > 300:
                    score += 30
                    reasons.append(f'sleep>{sleep_seconds}s')
                elif sleep_seconds > 60:
                    score += 15
                    reasons.append(f'sleep>{sleep_seconds}s')
            # Async patterns
            if re.search(r'asyncio\.gather|asyncio\.wait|asyncio\.as_completed', code, re.IGNORECASE):
                score += 20
                reasons.append('async_gather')
            # Subprocess calls
            if re.search(r'subprocess\.|Popen\s*\(', code, re.IGNORECASE):
                score += 20
                reasons.append('subprocess')
            # Large file operations
            if re.search(r'glob\.|os\.walk|Path\.rglob', code, re.IGNORECASE):
                score += 15
                reasons.append('file_scan')

        # Determine category
        if score >= 80:
            category = 'critical'
        elif score >= 50:
            category = 'high'
        elif score >= 25:
            category = 'medium'
        else:
            category = 'low'

        return min(score, 100), reasons, category

    # ── Logging ─────────────────────────────────────────────────────

    def _log_intervention(
        self,
        tool_args: dict[str, Any],
        score: int,
        reasons: list[str],
        action: str,
        config: dict,
    ) -> None:
        """Log intervention to file and console."""
        log_file = config.get('log_file', '/a0/usr/workdir/logs/session_guard.log')
        runtime = tool_args.get('runtime', '')

        # Ensure log directory exists
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # Truncate code for logging
        code_snippet = tool_args.get('code', '')[:200].replace('\n', ' ')
        if len(tool_args.get('code', '')) > 200:
            code_snippet += '...'

        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'tool': 'code_execution_tool',
            'runtime': runtime,
            'session': tool_args.get('session', 0),
            'risk_score': score,
            'risk_reasons': reasons,
            'action': action,
            'code_snippet': code_snippet,
        }

        # Write to log file
        try:
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
        except Exception:
            pass

        # Console output via PrintStyle
        msg = (
            f"Session Guard: {action.replace('_', ' ').title()} | "
            f"Risk {score}/100 | Session {tool_args.get('session', 0)} | "
            f"Reasons: {', '.join(reasons[:3]) or 'none'}"
        )
        if action == 'blocked':
            PrintStyle.error(msg)
        elif action == 'redirected':
            PrintStyle.warning(msg)
        elif action == 'warned' or score >= 50:
            PrintStyle.warning(msg)
        else:
            PrintStyle.hint(msg)

    def _update_stats(self, action: str, config: dict) -> None:
        """Update statistics file."""
        stats_file = config.get('stats_file', '/a0/usr/workdir/logs/session_guard_stats.json')

        try:
            stats = {}
            if os.path.exists(stats_file):
                with open(stats_file, 'r') as f:
                    stats = json.load(f)

            stats.setdefault('total_interventions', 0)
            stats.setdefault('actions', {'allowed': 0, 'warned': 0, 'redirected': 0, 'blocked': 0})
            stats.setdefault('last_intervention', None)

            stats['total_interventions'] += 1
            stats['actions'][action] = stats['actions'].get(action, 0) + 1
            stats['last_intervention'] = datetime.utcnow().isoformat()

            os.makedirs(os.path.dirname(stats_file), exist_ok=True)
            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2)
        except Exception:
            pass

    # ── Enforcement Actions ─────────────────────────────────────────

    def _find_next_session(self, current: int = 0) -> int:
        """Find next available session number (1-9)."""
        # Simple policy: return 1-9 cycling
        if current >= 9:
            return 1
        return max(1, current + 1)

    def _take_action(
        self,
        tool_args: dict[str, Any],
        score: int,
        reasons: list[str],
        config: dict,
    ) -> None:
        """Take enforcement action based on risk score and config mode."""
        mode = config.get('enforcement_mode', 'warn')

        if score == 0:
            # No risk - allow
            return

        if mode == 'block' and score >= 50:
            # Block high-risk commands
            self._log_intervention(tool_args, score, reasons, 'blocked', config)
            self._update_stats('blocked', config)
            raise RuntimeError(
                f"Session Guard BLOCKED execution: Risk score {score}/100. "
                f"High-risk patterns detected: {', '.join(reasons[:3])}. "
                f"Use a dedicated subagent for long-running operations."
            )

        if mode == 'redirect' and score >= 30:
            # Circuit breaker: check if in cooldown
            cb = config.get('circuit_breaker', {})
            cb_max = cb.get('max_redirect_failures', 3)
            cb_cooldown = cb.get('cooldown_seconds', 300)

            if self._cb_fallback_until and time.time() < self._cb_fallback_until:
                # In cooldown - fall back to warn
                self._log_intervention(tool_args, score, reasons, 'warned_cb_fallback', config)
                self._update_stats('warned', config)
                return

            # Reset if cooldown expired
            if self._cb_fallback_until and time.time() >= self._cb_fallback_until:
                self._cb_failures = 0
                self._cb_fallback_until = 0

            # Redirect to higher session
            new_session = self._find_next_session(tool_args.get('session', 0))
            old_session = tool_args.get('session', 0)

            if new_session == old_session:
                # No available session - increment failure counter
                self._cb_failures += 1
                if self._cb_failures >= cb_max:
                    self._cb_fallback_until = time.time() + cb_cooldown
                    self._log_intervention(tool_args, score, reasons, 'cb_triggered', config)
                self._log_intervention(tool_args, score, reasons, 'warned', config)
                self._update_stats('warned', config)
                return

            tool_args['session'] = new_session
            self._cb_failures = 0  # Reset on successful redirect
            self._log_intervention(tool_args, score, reasons, 'redirected', config)
            self._update_stats('redirected', config)

            # Also store original session for tracking
            if self.agent:
                guard_log = self.agent.data.setdefault('_session_guard_log', [])
                guard_log.append({
                    'timestamp': datetime.utcnow().isoformat(),
                    'original_session': old_session,
                    'new_session': new_session,
                    'risk_score': score,
                    'action': 'redirected',
                })
            return

        if score >= 30 or (mode == 'warn' and score > 0):
            # Warn mode or medium+ risk
            self._log_intervention(tool_args, score, reasons, 'warned', config)
            self._update_stats('warned', config)
            return

        # Low risk - log but allow
        self._log_intervention(tool_args, score, reasons, 'allowed', config)
        self._update_stats('allowed', config)

    # ── Main Extension Entry Point ─────────────────────────────────

    async def execute(
        self,
        tool_name: str = "",
        tool_args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Intercept code_execution_tool calls and enforce session 0 protection.

        This is called BEFORE the actual tool execution.
        """
        if tool_args is None:
            tool_args = {}

        # Only intercept code_execution_tool
        if tool_name != 'code_execution_tool':
            return

        config = self._get_config()
        if not config.get('enabled', True):
            return

        try:
            # Skip output/runtime polling mode - these are followups to existing sessions
            runtime = tool_args.get('runtime', '')
            if runtime == 'output':
                return

            # Get session (default 0 if not specified)
            session = tool_args.get('session', 0)

            # Only process session 0 executions
            if session != 0:
                return

            # Calculate risk
            score, reasons, category = self._calculate_risk_score(tool_args, config)

            # Take action based on risk and config
            self._take_action(tool_args, score, reasons, config)

        except Exception as e:
            # Don't let session guard errors break the agent
            # Log and continue
            try:
                PrintStyle.warning(f"Session Guard error (continuing): {e}")
                # Log to file
                log_file = config.get('log_file', '/a0/usr/workdir/logs/session_guard.log')
                with open(log_file, 'a') as f:
                    f.write(json.dumps({
                        'timestamp': datetime.utcnow().isoformat(),
                        'error': str(e),
                        'traceback': traceback.format_exc()[:500],
                    }) + '\n')
            except Exception:
                pass

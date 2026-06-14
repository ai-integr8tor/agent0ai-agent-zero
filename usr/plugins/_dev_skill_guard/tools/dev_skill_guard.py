"""Dev Skill Guard tool - validates a0-development skill documentation against framework reality."""

import json
import os
from pathlib import Path

import yaml
from helpers.tool import Tool, Response
from helpers.print_style import PrintStyle

# Import the scanner - try relative import, fall back to direct
_current_file = Path(__file__).resolve()
_helpers_path = _current_file.parent.parent / "helpers"
skill_scanner_path = _helpers_path / "skill_scanner.py"


class DevSkillGuard(Tool):
    """Tool for auditing and validating a0-development skill documentation."""

    def __init__(self, agent: "Agent", name: str, method: str | None,
                 args: dict[str, str], message: str,
                 loop_data: "LoopData" | None, **kwargs) -> None:
        super().__init__(agent, name, method, args, message, loop_data, **kwargs)
        self._scanner = None
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """Load plugin configuration."""
        current_file = Path(__file__).resolve()
        config_path = current_file.parent.parent / "default_config.yaml"
        
        if not config_path.exists():
            return {"log_file": "/a0/usr/workdir/logs/dev_skill_guard.log",
                    "audit_file": "/a0/usr/workdir/logs/dev_skill_guard_audit.json"}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {"log_file": "/a0/usr/workdir/logs/dev_skill_guard.log",
                    "audit_file": "/a0/usr/workdir/logs/dev_skill_guard_audit.json"}

    def _get_scanner(self):
        """Lazy-load the skill scanner."""
        if self._scanner is None:
            # Add helpers to path temporarily if needed
            if str(_helpers_path) not in sys.path:
                sys.path.insert(0, str(_helpers_path.parent))
            
            from skill_scanner import SkillScanner, SkillScannerError
            self._scanner = SkillScanner()
        return self._scanner

    def _log_result(self, message: str, level: str = "info"):
        """Log to file and console."""
        log_file = Path(self._config.get("log_file", "/a0/usr/workdir/logs/dev_skill_guard.log"))
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        log_entry = {"timestamp": timestamp, "level": level, "message": message}
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass
        
        # Also print to console
        if level == "error":
            PrintStyle.error(message)
        elif level == "warning":
            PrintStyle.warning(message)
        else:
            PrintStyle.hint(message)

    def _save_audit_file(self, results: dict):
        """Save audit results to JSON file."""
        audit_file = Path(self._config.get("audit_file", 
            "/a0/usr/workdir/logs/dev_skill_guard_audit.json"))
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(audit_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2)
            self._log_result(f"Audit saved to {audit_file}")
        except Exception as e:
            self._log_result(f"Failed to save audit: {e}", "error")

    def _load_last_audit(self) -> dict | None:
        """Load last audit results if available."""
        audit_file = Path(self._config.get("audit_file",
            "/a0/usr/workdir/logs/dev_skill_guard_audit.json"))
        
        if audit_file.exists():
            try:
                with open(audit_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return None

    async def execute_audit(self, **kwargs) -> Response:
        """Run full audit and return results.
        
        Args:
            detailed: bool - Include file listings in output
            save: bool - Save results to audit file (default: true)
        """
        import sys
        detailed = kwargs.get("detailed", False)
        save = kwargs.get("save", True)
        
        try:
            scanner = self._get_scanner()
        except Exception as e:
            return Response(
                message=f"Failed to initialize scanner: {e}",
                break_loop=False
            )
        
        self._log_result("Starting full audit...")
        
        try:
            results = scanner.run_full_audit()
        except Exception as e:
            self._log_result(f"Audit failed: {e}", "error")
            return Response(
                message=f"Audit failed: {e}",
                break_loop=False
            )
        
        if save:
            self._save_audit_file(results)
        
        # Build summary
        summary = results.get("summary", {})
        total_discrepancies = summary.get("total_discrepancies", 0)
        critical_issues = summary.get("critical_issues", 0)
        warnings = summary.get("warnings", 0)
        
        message_parts = [
            "## Dev Skill Guard Audit Results",
            f"**SKILL.md**: {results.get('skill_path', 'N/A')}",
            f"**Timestamp**: {results.get('timestamp', 'N/A')}",
            "",
            "### Summary",
            f"- Total discrepancies: {total_discrepancies}",
            f"- Critical issues: {critical_issues}",
            f"- Warnings: {warnings}",
            "",
        ]
        
        if total_discrepancies == 0:
            message_parts.append("✅ **Documentation is fully synchronized with framework.**")
        else:
            message_parts.append("⚠️ **Issues found - documentation needs updating.**")
        
        message_parts.extend([
            "",
            "### Hook Points",
            f"- Documented: {results['sections'].get('hook_points', {}).get('documented_count', 0)}",
            f"- Actual: {results['sections'].get('hook_points', {}).get('actual_count', 0)}",
        ])
        
        missing_hooks = results['sections'].get('hook_points', {}).get('missing_from_skill', [])
        new_hooks = results['sections'].get('hook_points', {}).get('new_in_filesystem', [])
        
        if missing_hooks:
            message_parts.append(f"- ⚠️ Missing from SKILL.md: {', '.join(missing_hooks)}")
        if new_hooks:
            message_parts.append(f"- ⚠️ Documented but missing from fs: {', '.join(new_hooks)}")
        
        message_parts.extend([
            "",
            "### Core Plugins",
            f"- Documented: {len(results['sections'].get('core_plugins', {}).get('documented', []))}",
            f"- Actual: {len(results['sections'].get('core_plugins', {}).get('actual', []))}",
        ])
        
        missing_plugins = results['sections'].get('core_plugins', {}).get('missing_from_skill', [])
        new_plugins = results['sections'].get('core_plugins', {}).get('new_in_skill', [])
        
        if missing_plugins:
            message_parts.append(f"- ⚠️ Missing from SKILL.md: {', '.join(missing_plugins)}")
        if new_plugins:
            message_parts.append(f"- ⚠️ Documented but missing from fs: {', '.join(new_plugins)}")
        
        if detailed:
            message_parts.extend([
                "",
                "### Core Tools",
                f"Found {results['sections'].get('core_tools', {}).get('count', 0)} tools",
                f"Tools: {', '.join(results['sections'].get('core_tools', {}).get('tools_found', [])[:10])}{'...' if len(results['sections'].get('core_tools', {}).get('tools_found', [])) > 10 else ''}",
                "",
                "### API Endpoints",
                f"Found {results['sections'].get('api_endpoints', {}).get('count', 0)} endpoints",
                "",
                "### Agent Profiles",
                f"Core profiles: {', '.join(results['sections'].get('agent_profiles', {}).get('core_profiles', []))}",
                f"User profiles: {len(results['sections'].get('agent_profiles', {}).get('user_profiles', []))}",
                "",
                "### User Space",
                f"User plugins: {results['sections'].get('user_plugins', {}).get('count', 0)}",
                f"User skills: {results['sections'].get('user_skills', {}).get('count', 0)}",
            ])
        
        message_parts.extend([
            "",
            "---",
            f"Run `fix` method to generate recommendations.",
            f"Audit file: {self._config.get('audit_file')}",
        ])
        
        return Response(
            message="\n".join(message_parts),
            break_loop=False,
            additional={"results": results}
        )

    async def execute_status(self, **kwargs) -> Response:
        """Show last audit status."""
        last_audit = self._load_last_audit()
        
        if last_audit is None:
            return Response(
                message="No previous audit found. Run `audit` to perform a scan.",
                break_loop=False
            )
        
        summary = last_audit.get("summary", {})
        timestamp = last_audit.get("timestamp", "unknown")
        
        message = f"""## Last Audit Status

**Timestamp**: {timestamp}
**SKILL.md**: {last_audit.get('skill_path', 'N/A')}

### Results Summary
- Total discrepancies: {summary.get('total_discrepancies', 0)}
- Critical issues: {summary.get('critical_issues', 0)}
- Warnings: {summary.get('warnings', 0)}

### Scanned Sections
- Hook points: {last_audit['sections'].get('hook_points', {}).get('actual_count', 0)} found
- Core plugins: {len(last_audit['sections'].get('core_plugins', {}).get('actual', []))} found
- Core tools: {last_audit['sections'].get('core_tools', {}).get('count', 0)} found
- API endpoints: {last_audit['sections'].get('api_endpoints', {}).get('count', 0)} found
- Agent profiles: {last_audit['sections'].get('agent_profiles', {}).get('total', 0)} total
- User plugins: {last_audit['sections'].get('user_plugins', {}).get('count', 0)} found

Run `audit` to perform a fresh scan."""
        
        return Response(
            message=message,
            break_loop=False
        )

    async def execute_fix(self, **kwargs) -> Response:
        """Generate fix recommendations from last audit.
        
        Args:
            show_skipped: bool - Show already documented items
        """
        import sys
        show_skipped = kwargs.get("show_skipped", False)
        
        try:
            scanner = self._get_scanner()
        except Exception as e:
            return Response(
                message=f"Failed to initialize scanner: {e}",
                break_loop=False
            )
        
        # Load last audit or run new one
        audit_results = self._load_last_audit()
        if audit_results is None:
            self._log_result("No previous audit found, running new audit...")
            try:
                audit_results = scanner.run_full_audit()
                self._save_audit_file(audit_results)
            except Exception as e:
                return Response(
                    message=f"Audit failed: {e}",
                    break_loop=False
                )
        
        recommendations = scanner.generate_fix_recommendations(audit_results)
        
        if not recommendations:
            return Response(
                message="✅ No issues found! Documentation is synchronized.",
                break_loop=False
            )
        
        message_parts = [
            "## Fix Recommendations",
            "",
        ]
        
        critical = [r for r in recommendations if r['severity'] == 'critical']
        warnings = [r for r in recommendations if r['severity'] == 'warning']
        
        if critical:
            message_parts.extend([
                "### 🔴 Critical Issues (Must Fix)",
                "",
            ])
            for r in critical:
                message_parts.extend([
                    f"**{r['category']}**: {r['issue']}",
                    f"  → Action: {r['action']}",
                    "",
                ])
        
        if warnings:
            message_parts.extend([
                "### ⚠️ Warnings (Should Review)",
                "",
            ])
            for r in warnings:
                message_parts.extend([
                    f"**{r['category']}**: {r['issue']}",
                    f"  → Action: {r['action']}",
                    "",
                ])
        
        message_parts.extend([
            "---",
            "**Note**: These are recommendations for manual review.",
            "Do NOT auto-apply changes to SKILL.md - verify each suggestion first.",
        ])
        
        return Response(
            message="\n".join(message_parts),
            break_loop=False,
            additional={"recommendations": recommendations}
        )

    async def execute(self, **kwargs) -> Response:
        """Main execute method - dispatches to sub-methods."""
        method = self.method if self.method else "status"
        
        if method == "audit":
            return await self.execute_audit(**kwargs)
        elif method == "status":
            return await self.execute_status(**kwargs)
        elif method == "fix":
            return await self.execute_fix(**kwargs)
        else:
            return Response(
                message=f"Unknown method: {method}. Available: audit, status, fix",
                break_loop=False
            )

# Plugin export - required for framework tool discovery
tool = DevSkillGuard
export = {"dev_skill_guard": DevSkillGuard}

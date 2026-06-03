"""Startup migration extension - runs skill documentation audit on startup.

This extension checks the a0-development skill documentation against the
actual framework filesystem state and logs any discrepancies.
"""

import json
from pathlib import Path

from helpers.extension import Extension
from helpers.print_style import PrintStyle
from helpers import files


class SkillAuditStartup(Extension):
    """Extension that runs dev skill guard audit on startup."""

    def __init__(self, agent: "Agent | None", **kwargs):
        super().__init__(agent, **kwargs)
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """Load plugin configuration."""
        current_file = Path(__file__).resolve()
        # Navigate from extensions/python/startup_migration/ to plugin root
        config_path = current_file.parent.parent.parent.parent / "default_config.yaml"
        
        if not config_path.exists():
            return {
                "enabled": True,
                "audit_on_startup": True,
                "log_file": "/a0/usr/workdir/logs/dev_skill_guard.log",
                "audit_file": "/a0/usr/workdir/logs/dev_skill_guard_audit.json",
            }
        
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {
                "enabled": True,
                "audit_on_startup": True,
                "log_file": "/a0/usr/workdir/logs/dev_skill_guard.log",
                "audit_file": "/a0/usr/workdir/logs/dev_skill_guard_audit.json",
            }

    def _log_line(self, level: str, message: str):
        """Append a log entry to the log file."""
        log_file = Path(self._config.get("log_file", "/a0/usr/workdir/logs/dev_skill_guard.log"))
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        from datetime import datetime
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "source": "startup_migration"
        }
        
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def execute(self, **kwargs) -> None:
        """Run the startup audit if enabled."""
        # Check if plugin is enabled
        if not self._config.get("enabled", True):
            return
        
        # Check if startup audit is enabled
        if not self._config.get("audit_on_startup", True):
            return
        
        self._log_line("info", "Starting dev_skill_guard startup audit...")
        
        try:
            # Import scanner - need to add helpers to path
            current_file = Path(__file__).resolve()
            helpers_path = current_file.parent.parent.parent.parent / "helpers"
            
            import sys
            if str(helpers_path.parent) not in sys.path:
                sys.path.insert(0, str(helpers_path.parent))
            
            from skill_scanner import SkillScanner, SkillScannerError
            
            scanner = SkillScanner()
            results = scanner.run_full_audit()
            
            # Save results
            audit_file = Path(self._config.get("audit_file",
                "/a0/usr/workdir/logs/dev_skill_guard_audit.json"))
            audit_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(audit_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2)
            
            # Check for discrepancies
            summary = results.get("summary", {})
            total_discrepancies = summary.get("total_discrepancies", 0)
            
            if total_discrepancies > 0:
                critical = summary.get("critical_issues", 0)
                warnings = summary.get("warnings", 0)
                
                self._log_line("warning",
                    f"SKILL.md has {total_discrepancies} discrepancies: "
                    f"{critical} critical, {warnings} warnings")
                
                # Print to console for visibility
                PrintStyle.hint(
                    f"⚠️  a0-development skill documentation: {total_discrepancies} discrepancies "
                    f"found ({critical} critical, {warnings} warnings). "
                    f"Run dev_skill_guard:audit for details."
                )
            else:
                self._log_line("info", "SKILL.md documentation is synchronized with framework")
                PrintStyle.hint("✅ a0-development skill documentation is synchronized")
                
        except skill_scanner.SkillScannerError as e:
            self._log_line("error", f"Skill scanner error: {e}")
            PrintStyle.error(f"Dev Skill Guard scanner error: {e}")
        except Exception as e:
            self._log_line("error", f"Startup audit failed: {e}")
            # Don't crash startup - just log the error
            PrintStyle.error(f"Dev Skill Guard startup audit failed: {e}")


# Extension entry point
async def execute(**kwargs) -> None:
    """Called by framework on startup."""
    # Agent is None during startup_migration
    extension = SkillAuditStartup(agent=None, **kwargs)
    extension.execute(**kwargs)
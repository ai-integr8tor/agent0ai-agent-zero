"""Skill scanner module - parses SKILL.md and scans filesystem for discrepancies."""

import os
import re
import yaml
from pathlib import Path
from typing import Any


class SkillScannerError(Exception):
    """Base error for skill scanner."""
    pass


class SkillScanner:
    """Scans a0-development SKILL.md and filesystem for documentation/sync issues."""

    def __init__(self, config_path: str | None = None):
        """Initialize scanner with configuration.
        
        Args:
            config_path: Path to plugin config. Auto-detected if None.
        """
        if config_path is None:
            # Auto-detect from this file's location
            current_file = Path(__file__).resolve()
            config_path = current_file.parent.parent / "default_config.yaml"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.skill_path = Path(self.config.get("skill_path", "/a0/skills/a0-development/SKILL.md"))
        self.scan_paths = self.config.get("scan_paths", {})
        self.skill_sections = self.config.get("skill_sections", {})
        
        self._skill_content: str | None = None
        self._audit_results: dict[str, Any] = {}

    def _load_config(self) -> dict:
        """Load plugin configuration from YAML file."""
        if not self.config_path.exists():
            raise SkillScannerError(f"Config not found: {self.config_path}")
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise SkillScannerError(f"Invalid YAML in config: {e}")

    def _load_skill_content(self) -> str:
        """Load and cache SKILL.md content."""
        if self._skill_content is None:
            if not self.skill_path.exists():
                raise SkillScannerError(f"SKILL.md not found: {self.skill_path}")
            with open(self.skill_path, 'r', encoding='utf-8') as f:
                self._skill_content = f.read()
        return self._skill_content

    def _extract_table_rows(self, content: str, table_name: str) -> list[tuple[str, ...]]:
        """Extract table rows from markdown content.
        
        Returns list of tuples where each tuple is a row.
        """
        # Find table after specific section header
        lines = content.split('\n')
        in_target_table = False
        rows = []
        
        for i, line in enumerate(lines):
            if table_name in line:
                in_target_table = True
                continue
            
            if in_target_table:
                # Skip separator line (---|---)
                if '|' in line and '---' in line:
                    continue
                # Skip empty lines
                if not line.strip():
                    in_target_table = False
                    continue
                # Parse table row
                if '|' in line:
                    cells = [cell.strip() for cell in line.split('|')]
                    # Filter out empty cells and remove any markdown formatting
                    cells = [cell.strip(' `') for cell in cells if cell.strip()]
                    if cells and cells[0] not in ['Hook Point', 'Source', 'Location', 'Plugin']:
                        rows.append(tuple(cells))
        
        return rows

    def scan_hook_points(self) -> dict[str, Any]:
        """Scan hook_points directory and compare against SKILL.md documented hook points.
        
        Returns:
            Dict with 'missing_from_skill', 'new_in_filesystem', 'documented_count', 'actual_count'
        """
        hook_points_dir = Path(self.scan_paths.get("hook_points", "/a0/extensions/python/"))
        
        if not hook_points_dir.exists():
            return {"error": f"Hook points directory not found: {hook_points_dir}"}
        
        # Get actual hook points from filesystem
        actual_hook_points = set()
        for item in hook_points_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_') and not item.name.startswith('.'):
                actual_hook_points.add(item.name)
        
        # Get documented hook points from config (which matches SKILL.md table)
        documented_hook_points = set(self.skill_sections.get("hook_points_table", []))
        
        # Calculate discrepancies
        missing_from_skill = actual_hook_points - documented_hook_points
        new_in_filesystem = documented_hook_points - actual_hook_points
        
        return {
            "missing_from_skill": sorted(missing_from_skill),
            "new_in_filesystem": sorted(new_in_filesystem),
            "documented_count": len(documented_hook_points),
            "actual_count": len(actual_hook_points),
        }

    def scan_core_plugins(self) -> dict[str, Any]:
        """Scan core plugins directory and compare against SKILL.md.
        
        Returns:
            Dict with 'missing_from_skill', 'new_in_skill', 'documented_list', 'actual_list'
        """
        plugins_dir = Path(self.scan_paths.get("core_plugins", "/a0/plugins/"))
        
        if not plugins_dir.exists():
            return {"error": f"Plugins directory not found: {plugins_dir}"}
        
        # Get actual plugins from filesystem
        actual_plugins = set()
        for item in plugins_dir.iterdir():
            if item.is_dir() and item.name.startswith('_'):
                actual_plugins.add(item.name)
        
        # Get documented plugins from config
        documented_plugins = set(self.skill_sections.get("core_plugins", []))
        
        # Calculate discrepancies
        missing_from_skill = actual_plugins - documented_plugins
        new_in_skill = documented_plugins - actual_plugins
        
        return {
            "missing_from_skill": sorted(missing_from_skill),
            "new_in_skill": sorted(new_in_skill),
            "documented": sorted(documented_plugins),
            "actual": sorted(actual_plugins),
        }

    def scan_core_tools(self) -> dict[str, Any]:
        """Scan core tools directory.
        
        Returns:
            Dict with 'tools_found', 'expected_files'
        """
        tools_dir = Path(self.scan_paths.get("core_tools", "/a0/tools/"))
        
        if not tools_dir.exists():
            return {"error": f"Tools directory not found: {tools_dir}"}
        
        # Get actual tools
        tool_files = []
        for item in tools_dir.iterdir():
            if item.is_file() and item.suffix == '.py' and not item.name.startswith('_'):
                tool_files.append(item.stem)
        
        return {
            "tools_found": sorted(tool_files),
            "count": len(tool_files),
        }

    def scan_api_endpoints(self) -> dict[str, Any]:
        """Scan API endpoints directory.
        
        Returns:
            Dict with 'endpoints_found'
        """
        api_dir = Path(self.scan_paths.get("api_endpoints", "/a0/api/"))
        
        if not api_dir.exists():
            return {"error": f"API directory not found: {api_dir}"}
        
        endpoint_files = []
        for item in api_dir.iterdir():
            if item.is_file() and item.suffix == '.py' and not item.name.startswith('_'):
                endpoint_files.append(item.stem)
        
        return {
            "endpoints_found": sorted(endpoint_files),
            "count": len(endpoint_files),
        }

    def scan_agent_profiles(self) -> dict[str, Any]:
        """Scan agent profiles directories.
        
        Returns:
            Dict with 'core_profiles', 'user_profiles'
        """
        core_dir = Path(self.scan_paths.get("agent_profiles", "/a0/agents/"))
        user_dir = Path("/a0/usr/agents/")  # Hardcoded path
        
        core_profiles = []
        if core_dir.exists():
            for item in core_dir.iterdir():
                if item.is_dir() and not item.name.startswith('_'):
                    core_profiles.append(item.name)
        
        user_profiles = []
        if user_dir.exists():
            for item in user_dir.iterdir():
                if item.is_dir() and not item.name.startswith('_'):
                    user_profiles.append(item.name)
        
        return {
            "core_profiles": sorted(core_profiles),
            "user_profiles": sorted(user_profiles),
            "total": len(core_profiles) + len(user_profiles),
        }

    def scan_user_plugins(self) -> dict[str, Any]:
        """Scan user plugins directory."""
        plugins_dir = Path(self.scan_paths.get("user_plugins", "/a0/usr/plugins/"))
        
        if not plugins_dir.exists():
            return {"error": f"User plugins directory not found: {plugins_dir}"}
        
        plugins = []
        for item in plugins_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_') and not item.name.startswith('.'):
                plugins.append(item.name)
        
        return {
            "user_plugins": sorted(plugins),
            "count": len(plugins),
        }

    def scan_user_skills(self) -> dict[str, Any]:
        """Scan user skills directory."""
        skills_dir = Path(self.scan_paths.get("user_skills", "/a0/usr/skills/"))
        
        if not skills_dir.exists():
            return {"error": f"User skills directory not found: {skills_dir}"}
        
        skills = []
        for item in skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_') and not item.name.startswith('.'):
                skills.append(item.name)
        
        return {
            "user_skills": sorted(skills),
            "count": len(skills),
        }

    def run_full_audit(self) -> dict[str, Any]:
        """Run complete audit across all scan targets.
        
        Returns:
            Complete audit results dictionary
        """
        results = {
            "status": "ok",
            "skill_path": str(self.skill_path),
            "timestamp": self._get_timestamp(),
            "sections": {},
            "summary": {
                "total_discrepancies": 0,
                "critical_issues": 0,
                "warnings": 0,
            }
        }
        
        # Scan hook points
        results["sections"]["hook_points"] = self.scan_hook_points()
        hook_discrepancies = (
            len(results["sections"]["hook_points"].get("missing_from_skill", [])) +
            len(results["sections"]["hook_points"].get("new_in_filesystem", []))
        )
        
        # Scan core plugins
        results["sections"]["core_plugins"] = self.scan_core_plugins()
        plugin_discrepancies = (
            len(results["sections"]["core_plugins"].get("missing_from_skill", [])) +
            len(results["sections"]["core_plugins"].get("new_in_skill", []))
        )
        
        # Scan tools
        results["sections"]["core_tools"] = self.scan_core_tools()
        
        # Scan API
        results["sections"]["api_endpoints"] = self.scan_api_endpoints()
        
        # Scan profiles
        results["sections"]["agent_profiles"] = self.scan_agent_profiles()
        
        # Scan user space
        results["sections"]["user_plugins"] = self.scan_user_plugins()
        results["sections"]["user_skills"] = self.scan_user_skills()
        
        # Calculate summary
        results["summary"]["total_discrepancies"] = hook_discrepancies + plugin_discrepancies
        results["summary"]["critical_issues"] = len(results["sections"]["hook_points"].get("missing_from_skill", []))
        results["summary"]["warnings"] = results["summary"]["total_discrepancies"] - results["summary"]["critical_issues"]
        
        self._audit_results = results
        return results

    def generate_fix_recommendations(self, audit_results: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Generate recommendations for fixing discrepancies.
        
        Returns:
            List of recommendation objects with severity and action
        """
        if audit_results is None:
            audit_results = self._audit_results
        
        if not audit_results:
            return []
        
        recommendations = []
        
        # Hook points recommendations
        hook_section = audit_results.get("sections", {}).get("hook_points", {})
        if hook_section.get("missing_from_skill"):
            for hook in hook_section["missing_from_skill"]:
                recommendations.append({
                    "severity": "critical",
                    "category": "hook_points",
                    "issue": f"Hook point '{hook}' exists in filesystem but not documented in SKILL.md",
                    "action": f"Add '{hook}' to the hook points table in SKILL.md",
                    "file": str(self.skill_path),
                })
        
        if hook_section.get("new_in_filesystem"):
            for hook in hook_section["new_in_filesystem"]:
                recommendations.append({
                    "severity": "warning",
                    "category": "hook_points",
                    "issue": f"Hook point '{hook}' documented but not found in filesystem",
                    "action": f"Verify if '{hook}' was removed or renamed",
                    "file": str(self.skill_path),
                })
        
        # Plugin recommendations
        plugin_section = audit_results.get("sections", {}).get("core_plugins", {})
        if plugin_section.get("missing_from_skill"):
            for plugin in plugin_section["missing_from_skill"]:
                recommendations.append({
                    "severity": "warning",
                    "category": "core_plugins",
                    "issue": f"Plugin '{plugin}' exists but not documented in SKILL.md",
                    "action": f"Add '{plugin}' to the core plugins table in SKILL.md",
                    "file": str(self.skill_path),
                })
        
        if plugin_section.get("new_in_skill"):
            for plugin in plugin_section["new_in_skill"]:
                recommendations.append({
                    "severity": "warning",
                    "category": "core_plugins",
                    "issue": f"Plugin '{plugin}' documented but not found in filesystem",
                    "action": f"Verify if '{plugin}' was removed or renamed",
                    "file": str(self.skill_path),
                })
        
        return recommendations

    def _get_timestamp(self) -> str:
        """Get current timestamp as ISO string."""
        from datetime import datetime
        return datetime.now().isoformat()
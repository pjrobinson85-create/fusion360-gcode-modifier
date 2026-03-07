import json
import os
from pathlib import Path

class ConfigManager:
    """Manages the configuration for safe heights, feedrates, and tools."""
    
    def __init__(self, config_path: str = None):
        if not config_path:
            # Default to the config folder in the project root
            base_dir = Path(__file__).parent.parent
            config_path = base_dir / "config" / "default_config.json"
            
        self.config_path = config_path
        self._config = self._load_config()
        
    def _load_config(self) -> dict:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    @property
    def safe_z_height(self) -> float:
        """The absolute Z height the machine must retract to before X/Y rapids."""
        return float(self._config.get("safe_z_height", 20.0))
        
    @property
    def xy_rapid_threshold(self) -> float:
        """The feedrate threshold above which G01 X/Y moves are considered nerfed rapids."""
        return float(self._config.get("rapid_feedrate_thresholds", {}).get("X_Y_RAPID", 500.0))

    @property
    def z_rapid_threshold(self) -> float:
        """The feedrate threshold above which G01 Z moves are considered nerfed rapids."""
        return float(self._config.get("rapid_feedrate_thresholds", {}).get("Z_RAPID", 500.0))
        
    @property
    def tool_change_position(self) -> dict:
        """The safe machine coordinates to pause at for an M06 tool change."""
        return self._config.get("tool_change_position", {"X": 0.0, "Y": 0.0, "Z": 50.0})

    def get_tool(self, tool_id: int) -> dict:
        """Retrieve tool properties by ID."""
        tools = self._config.get("tools", [])
        for t in tools:
            if t.get("id") == tool_id:
                return t
        return None

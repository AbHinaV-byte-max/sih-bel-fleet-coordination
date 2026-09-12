"""
Configuration Schema and Loader for SIH 26123 Fleet Coordination System.
Provides strongly typed Pydantic models for warehouse layout, robot types, and fleet configuration.
"""

from typing import List, Dict, Tuple, Optional
from pathlib import Path
import yaml
from pydantic import BaseModel, Field


class HumanZoneConfig(BaseModel):
    id: str
    name: str
    active: bool = True
    bounds: List[int] = Field(..., description="[min_x, min_y, max_x, max_y]")
    speed_derating_factor: float = 0.5

    def contains(self, x: int, y: int) -> bool:
        if not self.active:
            return False
        min_x, min_y, max_x, max_y = self.bounds
        return min_x <= x <= max_x and min_y <= y <= max_y


class StationConfig(BaseModel):
    id: str
    location: Tuple[int, int]


class RobotTypeConfig(BaseModel):
    description: str
    max_speed: float
    payload_capacity_kg: float
    battery_capacity_ah: float
    yield_priority_weight: int = 1


class InitialRobotConfig(BaseModel):
    id: str
    type: str
    start_pos: Tuple[int, int]
    battery_level_pct: float = 100.0


class PredictiveMaintenanceConfig(BaseModel):
    distance_km_threshold: float = 15.0
    operating_cycles_threshold: int = 40


class CoordinationConfig(BaseModel):
    intent_horizon_steps: int = 5
    time_step_duration_seconds: float = 0.5
    congestion_window_seconds: float = 60.0
    congestion_penalty_multiplier: float = 4.0
    predictive_maintenance: PredictiveMaintenanceConfig = Field(
        default_factory=PredictiveMaintenanceConfig
    )


class BrokerConfig(BaseModel):
    mode: str = "embedded"
    host: str = "127.0.0.1"
    port: int = 1883
    topic_prefix: str = "fleet"


class WarehouseLayout(BaseModel):
    name: str
    width: int
    height: int
    grid_resolution_meters: float = 1.0
    obstacles: List[Tuple[int, int]] = Field(default_factory=list)
    pickup_stations: List[StationConfig] = Field(default_factory=list)
    dropoff_stations: List[StationConfig] = Field(default_factory=list)
    charging_pads: List[StationConfig] = Field(default_factory=list)
    human_zones: List[HumanZoneConfig] = Field(default_factory=list)


class FleetConfig(BaseModel):
    robot_types: Dict[str, RobotTypeConfig]
    initial_robots: List[InitialRobotConfig]


class AppConfig(BaseModel):
    warehouse: WarehouseLayout
    fleet: FleetConfig
    coordination: CoordinationConfig
    broker: BrokerConfig


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from YAML file, falling back to default location."""
    if config_path is None:
        default_path = Path(__file__).parent / "warehouse_config.yaml"
        config_path = str(default_path)

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Flatten nested obstacle lists if formatted as groups
    raw_obstacles = data.get("warehouse", {}).get("obstacles", [])
    flat_obstacles: List[Tuple[int, int]] = []
    for item in raw_obstacles:
        if isinstance(item, list) and len(item) == 2 and isinstance(item[0], int):
            flat_obstacles.append((item[0], item[1]))
        elif isinstance(item, list):
            # sublist of points
            for pt in item:
                if isinstance(pt, (list, tuple)) and len(pt) == 2:
                    flat_obstacles.append((int(pt[0]), int(pt[1])))
    data["warehouse"]["obstacles"] = flat_obstacles

    # Normalize station locations to tuples
    for st_type in ["pickup_stations", "dropoff_stations", "charging_pads"]:
        stations = data.get("warehouse", {}).get(st_type, [])
        for st in stations:
            if "location" in st and isinstance(st["location"], list):
                st["location"] = tuple(st["location"])

    # Normalize robot initial positions
    for r in data.get("fleet", {}).get("initial_robots", []):
        if "start_pos" in r and isinstance(r["start_pos"], list):
            r["start_pos"] = tuple(r["start_pos"])

    return AppConfig.model_validate(data)

"""Constants for Simple Heat Control."""

DOMAIN = "simple_heat_control"
STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

FRONTEND_URL = "/simple_heat_control_static"
CARD_FILE = "simple-heat-control-card.js"

# config entry type
CONF_ENTRY_TYPE = "entry_type"
ENTRY_ROOM = "room"
ENTRY_BOILER = "boiler"

# room options
CONF_NAME = "name"
CONF_TEMP_SENSOR = "temperature_sensor"
CONF_TRV = "trv"
CONF_VALVE_POSITION = "valve_position_sensor"
CONF_RELAY = "relay"
CONF_OUTDOOR_SENSOR = "outdoor_sensor"
CONF_REGULATION = "regulation"
CONF_HYSTERESIS = "hysteresis"
CONF_CLOSE_WHEN_SATISFIED = "close_when_satisfied"
CONF_STALE_MINUTES = "stale_minutes"
CONF_SENSOR_MODE = "sensor_mode"  # how several room sensors are combined, see sensors.py
CONF_SMART_HEATING = "smart_heating"  # °C above target while the boiler heats for others; 0 = off

DEFAULT_REGULATION = "medium"
DEFAULT_HYSTERESIS = 0.5
DEFAULT_CLOSE_WHEN_SATISFIED = True
DEFAULT_STALE_MINUTES = 180
DEFAULT_SENSOR_MODE = "average"
DEFAULT_SMART_HEATING = 0.5
DEFAULT_SCHEDULE_TEMP = 20.0

# boiler options
CONF_BOILER_CLIMATE = "boiler_climate"
CONF_VETO_TEMP = "quick_veto_temperature"
CONF_VETO_HOURS = "quick_veto_hours"
CONF_BOILER_STATUS_SENSOR = "boiler_status_sensor"

DEFAULT_VETO_TEMP = 28.0
DEFAULT_VETO_HOURS = 0.5

# timing
TICK_SECONDS = 60            # schedule transitions, stale check, boiler refresh
REGULATION_PERIOD_MIN = 5    # same as VT's auto_regulation_periode_min default
BOILER_MIN_CALL_SECONDS = 60  # never call the myVaillant cloud more often than this
BOILER_REFRESH_BEFORE_MIN = 5  # re-send the quick veto this long before it runs out

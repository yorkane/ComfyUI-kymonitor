import json
import os

class Config:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Config, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, config_file_path="config.json"):
        if hasattr(self, '_initialized') and self._initialized:
            return
        self._initialized = True

        self.config_data = {}
        # Load from config.json if it exists
        try:
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r') as f:
                    self.config_data = json.load(f)
        except Exception as e:
            print(f"[KY_Monitor] Error loading {config_file_path}: {e}")

        # Default values
        self.frequency_seconds = self._get_config("KY_MONITOR_FREQUENCY_SECONDS", "frequency_seconds", 5)
        self.history_max_items = self._get_config("KY_MONITOR_HISTORY_MAX_ITEMS", "history_max_items", 100)

        # Prompt Server Channel
        self.prompt_server_enabled = self._get_bool_config("KY_MONITOR_PROMPT_SERVER_ENABLED", ["prompt_server_channel", "enabled"], True)
        self.prompt_server_event_name = self._get_config("KY_MONITOR_PROMPT_SERVER_EVENT_NAME", ["prompt_server_channel", "event_name"], "ky_monitor_update")

        # Redis Channel
        self.redis_enabled = self._get_bool_config("KY_MONITOR_REDIS_ENABLED", ["redis_channel", "enabled"], False)
        self.redis_host = self._get_config("KY_MONITOR_REDIS_HOST", ["redis_channel", "host"], "localhost")
        self.redis_port = self._get_int_config("KY_MONITOR_REDIS_PORT", ["redis_channel", "port"], 6379)
        self.redis_password = self._get_config("KY_MONITOR_REDIS_PASSWORD", ["redis_channel", "password"], None)
        self.redis_db = self._get_int_config("KY_MONITOR_REDIS_DB", ["redis_channel", "db"], 0)
        self.redis_channel_name = self._get_config("KY_MONITOR_REDIS_CHANNEL_NAME", ["redis_channel", "channel_name"], "comfyui_monitor")

        # RocketMQ Channel
        self.rocketmq_enabled = self._get_bool_config("KY_MONITOR_ROCKETMQ_ENABLED", ["rocketmq_channel", "enabled"], False)
        self.rocketmq_namesrv_addr = self._get_config("KY_MONITOR_ROCKETMQ_NAMESRV_ADDR", ["rocketmq_channel", "namesrv_addr"], "localhost:9876")
        self.rocketmq_topic = self._get_config("KY_MONITOR_ROCKETMQ_TOPIC", ["rocketmq_channel", "topic"], "comfyui_monitor_topic")
        self.rocketmq_group_id = self._get_config("KY_MONITOR_ROCKETMQ_GROUP_ID", ["rocketmq_channel", "group_id"], "KY_MONITOR_PRODUCER_GROUP")

    def _get_config(self, env_var, json_path, default_value):
        value = os.getenv(env_var)
        if value is not None:
            return value
        
        if isinstance(json_path, str):
            return self.config_data.get(json_path, default_value)
        
        # json_path is a list of keys for nested dict
        temp_data = self.config_data
        for key in json_path:
            if isinstance(temp_data, dict) and key in temp_data:
                temp_data = temp_data[key]
            else:
                return default_value
        return temp_data


    def _get_bool_config(self, env_var, json_path, default_value):
        value_str = self._get_config(env_var, json_path, None)
        if value_str is None:
            return default_value
        return value_str.lower() in ['true', '1', 't', 'y', 'yes']

    def _get_int_config(self, env_var, json_path, default_value):
        value_str = self._get_config(env_var, json_path, None)
        if value_str is None:
            return default_value
        try:
            return int(value_str)
        except ValueError:
            print(f"[KY_Monitor] Warning: Could not parse integer for {env_var}, using default {default_value}")
            return default_value

# Global config instance
# This will be initialized when the module is first imported.
# ComfyUI loads nodes at startup, so this should be fine.
# In a standalone script, you might call `Config()` explicitly.
APP_CONFIG = Config()


if __name__ == '__main__':
    # Example of how to use it (for testing)
    # Create a dummy config.json for testing
    dummy_config = {
        "frequency_seconds": 10,
        "prompt_server_channel": {
            "enabled": True,
            "event_name": "custom_event"
        },
        "redis_channel": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 6380
        }
    }
    with open("config.json", "w") as f:
        json.dump(dummy_config, f)

    # Set some env vars for testing override
    os.environ["KY_MONITOR_FREQUENCY_SECONDS"] = "3"
    os.environ["KY_MONITOR_REDIS_ENABLED"] = "false"
    
    # Re-initialize or create new instance to pick up changes for testing
    # In normal use, this happens once at import.
    config_instance = Config(config_file_path="config.json")


    print(f"Frequency: {config_instance.frequency_seconds} (Expected: 3 from env)")
    print(f"History Max Items: {config_instance.history_max_items} (Expected: 100 default)")
    
    print(f"Prompt Server Enabled: {config_instance.prompt_server_enabled} (Expected: True from json)")
    print(f"Prompt Server Event Name: {config_instance.prompt_server_event_name} (Expected: custom_event from json)")

    print(f"Redis Enabled: {config_instance.redis_enabled} (Expected: False from env)")
    print(f"Redis Host: {config_instance.redis_host} (Expected: 127.0.0.1 from json)")
    print(f"Redis Port: {config_instance.redis_port} (Expected: 6380 from json)")
    print(f"Redis Channel: {config_instance.redis_channel_name} (Expected: comfyui_monitor default)")

    print(f"RocketMQ Enabled: {config_instance.rocketmq_enabled} (Expected: False default)")

    # Clean up dummy config and env vars
    os.remove("config.json")
    del os.environ["KY_MONITOR_FREQUENCY_SECONDS"]
    del os.environ["KY_MONITOR_REDIS_ENABLED"]
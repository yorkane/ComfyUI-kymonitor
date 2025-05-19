import json
import os
import logging

# 配置日志处理器
logger = logging.getLogger("KY_monitor_config")
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# 添加处理器到logger
logger.addHandler(console_handler)

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
        # 从config.json加载配置
        try:
            if os.path.exists(config_file_path):
                with open(config_file_path, 'r') as f:
                    self.config_data = json.load(f)
        except Exception as e:
            logger.error(f"加载配置文件 {config_file_path} 失败: {e}")

        # 默认值
        self.frequency_seconds = self._get_config("KY_MONITOR_FREQUENCY_SECONDS", "frequency_seconds", 5)
        self.history_max_items = self._get_config("KY_MONITOR_HISTORY_MAX_ITEMS", "history_max_items", 100)

        # Prompt Server Channel
        self.prompt_server_enabled = self._get_bool_config("KY_MONITOR_PROMPT_SERVER_ENABLED", ["prompt_server_channel", "enabled"], True)
        self.prompt_server_event_name = self._get_config("KY_MONITOR_PROMPT_SERVER_EVENT_NAME", ["prompt_server_channel", "event_name"], "ky_monitor.queue")
        
        logger.info(self)
        logger.info(self.prompt_server_event_name)
        logger.info(self.prompt_server_enabled)

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
        
        # json_path 是嵌套字典的键列表
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
            logger.warning(f"无法解析整数配置 {env_var}，使用默认值 {default_value}")
            return default_value 
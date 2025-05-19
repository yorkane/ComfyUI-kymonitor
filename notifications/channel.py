import json
import traceback
import logging
from abc import ABC, abstractmethod
from ..config import APP_CONFIG

logger = logging.getLogger("KY_monitor_channel")

# ComfyUI的prompt_server占位符
prompt_server = None 

def set_prompt_server(server_instance):
    global prompt_server
    prompt_server = server_instance

class NotificationChannel(ABC):
    @abstractmethod
    def send(self, info_data):
        pass

    @abstractmethod
    def is_enabled(self):
        pass

class PromptServerChannel(NotificationChannel):
    def __init__(self):
        self.enabled = APP_CONFIG.prompt_server_enabled
        self.event_name = APP_CONFIG.prompt_server_event_name
        if self.enabled:
            logger.info(f"PromptServerChannel已启用，事件名称: {self.event_name}")

    def send(self, info_data_list):
        if not self.enabled or not prompt_server or not hasattr(prompt_server, 'send_sync'):
            if self.enabled:
                logger.warning("PromptServerChannel: prompt_server不可用或缺少send_sync方法")
            return

        try:
            prompt_server.send_sync(self.event_name, info_data_list)
        except Exception as e:
            logger.error(f"通过PromptServerChannel发送失败: {e}")
            traceback.print_exc()

    def is_enabled(self):
        return self.enabled

class RedisChannel(NotificationChannel):
    def __init__(self):
        self.enabled = APP_CONFIG.redis_enabled
        self.redis_client = None
        if self.enabled:
            try:
                import redis
                self.redis_client = redis.StrictRedis(
                    host=APP_CONFIG.redis_host,
                    port=APP_CONFIG.redis_port,
                    password=APP_CONFIG.redis_password,
                    db=APP_CONFIG.redis_db,
                    decode_responses=True
                )
                self.redis_client.ping()
                self.channel_name = APP_CONFIG.redis_channel_name
                logger.info(f"RedisChannel已启用，连接到 {APP_CONFIG.redis_host}:{APP_CONFIG.redis_port}，频道: {self.channel_name}")
            except ImportError:
                logger.error("未找到Redis库。请安装: pip install redis")
                self.enabled = False
            except Exception as e:
                logger.error(f"初始化RedisChannel失败: {e}")
                self.enabled = False

    def send(self, info_data_list):
        if not self.enabled or not self.redis_client:
            return
        try:
            message = json.dumps(info_data_list)
            self.redis_client.publish(self.channel_name, message)
        except Exception as e:
            logger.error(f"通过RedisChannel发送失败: {e}")

    def is_enabled(self):
        return self.enabled and self.redis_client is not None

class RocketMQChannel(NotificationChannel):
    def __init__(self):
        self.enabled = APP_CONFIG.rocketmq_enabled
        self.producer = None
        if self.enabled:
            try:
                from rocketmq.client import Producer, Message
                self.producer = Producer(APP_CONFIG.rocketmq_group_id)
                self.producer.set_name_server_address(APP_CONFIG.rocketmq_namesrv_addr)
                self.topic = APP_CONFIG.rocketmq_topic
                logger.info(f"RocketMQChannel已启用，NameServer: {APP_CONFIG.rocketmq_namesrv_addr}，Topic: {self.topic}")
            except ImportError:
                logger.error("未找到RocketMQ客户端库。请安装: pip install rocketmq-client-python")
                self.enabled = False
            except Exception as e:
                logger.error(f"初始化RocketMQChannel失败: {e}")
                self.enabled = False

    def send(self, info_data_list):
        if not self.enabled or not self.producer:
            return
        
        from rocketmq.client import Message
        try:
            body = json.dumps(info_data_list)
            msg = Message(self.topic)
            msg.set_keys("ky_monitor_update")
            msg.set_tags("comfyui_status")
            msg.set_body(body)
            
            if hasattr(self.producer, 'is_running') and not self.producer.is_running():
                logger.info("启动RocketMQ生产者...")
                self.producer.start()
            elif not hasattr(self.producer, 'is_running'):
                try:
                    if hasattr(self.producer, 'start') and not getattr(self.producer, '_running', False):
                        logger.info("尝试启动RocketMQ生产者...")
                        self.producer.start()
                except Exception as start_e:
                    logger.error(f"无法确保RocketMQ生产者启动: {start_e}")
                    return

            ret = self.producer.send_sync(msg)
        except Exception as e:
            logger.error(f"通过RocketMQChannel发送失败: {e}")
            traceback.print_exc()

    def is_enabled(self):
        return self.enabled and self.producer is not None

    def shutdown(self):
        if self.producer and hasattr(self.producer, 'shutdown'):
            try:
                logger.info("关闭RocketMQ生产者...")
                self.producer.shutdown()
            except Exception as e:
                logger.error(f"关闭RocketMQ生产者失败: {e}") 
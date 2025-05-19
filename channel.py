import json
import traceback
from abc import ABC, abstractmethod
from .config import APP_CONFIG

# Placeholder for ComfyUI's prompt_server. 
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
            print(f"[KY_Monitor] PromptServerChannel enabled, event name: {self.event_name}")

    def send(self, info_data_list):
        if not self.enabled or not prompt_server or not hasattr(prompt_server, 'send_sync'):
            if self.enabled:
                 print("[KY_Monitor] PromptServerChannel: prompt_server not available or send_sync missing.")
            return

        # The design doc info object is singular. If we send a list of infos,
        # the receiver needs to handle a list or we send one by one.
        # Let's assume for now send_sync expects a single data payload that could be the list itself.
        try:
            # prompt_server.send_sync expects (event_name, data, sid=None)
            # We'll send the whole list as the data payload for a single event.
            prompt_server.send_sync(self.event_name, info_data_list) 
            # print(f"[KY_Monitor] Sent {len(info_data_list)} info objects via PromptServerChannel to event {self.event_name}")
        except Exception as e:
            print(f"[KY_Monitor] Error sending via PromptServerChannel: {e}")
            traceback.print_exc()

    def is_enabled(self):
        return self.enabled

class RedisChannel(NotificationChannel):
    def __init__(self):
        self.enabled = APP_CONFIG.redis_enabled
        self.redis_client = None
        if self.enabled:
            try:
                import redis # type: ignore
                self.redis_client = redis.StrictRedis(
                    host=APP_CONFIG.redis_host,
                    port=APP_CONFIG.redis_port,
                    password=APP_CONFIG.redis_password,
                    db=APP_CONFIG.redis_db,
                    decode_responses=True
                )
                self.redis_client.ping() # Verify connection
                self.channel_name = APP_CONFIG.redis_channel_name
                print(f"[KY_Monitor] RedisChannel enabled, connected to {APP_CONFIG.redis_host}:{APP_CONFIG.redis_port}, channel: {self.channel_name}")
            except ImportError:
                print("[KY_Monitor] Redis library not found. Please install it: pip install redis")
                self.enabled = False
            except Exception as e:
                print(f"[KY_Monitor] Error initializing RedisChannel: {e}")
                self.enabled = False

    def send(self, info_data_list):
        if not self.enabled or not self.redis_client:
            return
        try:
            # Send the entire list of info objects as a single JSON string message
            message = json.dumps(info_data_list)
            self.redis_client.publish(self.channel_name, message)
            # print(f"[KY_Monitor] Sent {len(info_data_list)} info objects via RedisChannel to {self.channel_name}")
        except Exception as e:
            print(f"[KY_Monitor] Error sending via RedisChannel: {e}")
            # Optional: Implement retry logic or disable channel temporarily

    def is_enabled(self):
        return self.enabled and self.redis_client is not None

class RocketMQChannel(NotificationChannel):
    def __init__(self):
        self.enabled = APP_CONFIG.rocketmq_enabled
        self.producer = None
        if self.enabled:
            try:
                from rocketmq.client import Producer, Message # type: ignore
                self.producer = Producer(APP_CONFIG.rocketmq_group_id)
                self.producer.set_name_server_address(APP_CONFIG.rocketmq_namesrv_addr)
                # Potentially add producer.start() here if required by the library version
                # and handle its shutdown.
                # Some SDKs start on first send or require explicit start.
                # For now, assume start is not needed or handled by send.
                # self.producer.start() # Uncomment if your RocketMQ client library needs explicit start
                self.topic = APP_CONFIG.rocketmq_topic
                print(f"[KY_Monitor] RocketMQChannel enabled, NameServer: {APP_CONFIG.rocketmq_namesrv_addr}, Topic: {self.topic}")
            except ImportError:
                print("[KY_Monitor] RocketMQ client library not found. Please install it: pip install rocketmq-client-python")
                self.enabled = False
            except Exception as e:
                print(f"[KY_Monitor] Error initializing RocketMQChannel: {e}")
                self.enabled = False

    def send(self, info_data_list):
        if not self.enabled or not self.producer:
            return
        
        from rocketmq.client import Message # Import here to avoid error if lib not installed and channel disabled
        try:
            # Send the entire list of info objects as a single JSON string message body
            body = json.dumps(info_data_list)
            msg = Message(self.topic)
            msg.set_keys("ky_monitor_update") # Example key
            msg.set_tags("comfyui_status")    # Example tags
            msg.set_body(body)
            
            # Start producer if not started (some SDKs require this)
            if hasattr(self.producer, 'is_running') and not self.producer.is_running():
                 print("[KY_Monitor] Starting RocketMQ producer for send...")
                 self.producer.start()
            elif not hasattr(self.producer, 'is_running'): # Fallback for older/different SDKs
                 try:
                    if hasattr(self.producer, 'start') and not getattr(self.producer, '_running', False): # Check a common private flag
                        print("[KY_Monitor] Attempting to start RocketMQ producer...")
                        self.producer.start()
                 except Exception as start_e:
                    print(f"[KY_Monitor] Could not ensure RocketMQ producer is started: {start_e}")
                    # Potentially disable channel if start fails repeatedly
                    return

            ret = self.producer.send_sync(msg)
            # print(f"[KY_Monitor] Sent {len(info_data_list)} info objects via RocketMQChannel. Topic: {self.topic}, Status: {ret.status}, MsgID: {ret.msg_id}")
        except Exception as e:
            print(f"[KY_Monitor] Error sending via RocketMQChannel: {e}")
            traceback.print_exc()
            # Optional: Implement retry logic or disable channel temporarily

    def is_enabled(self):
        return self.enabled and self.producer is not None

    def shutdown(self): # Call this when ComfyUI is shutting down
        if self.producer and hasattr(self.producer, 'shutdown'):
            try:
                print("[KY_Monitor] Shutting down RocketMQ producer...")
                self.producer.shutdown()
            except Exception as e:
                print(f"[KY_Monitor] Error shutting down RocketMQ producer: {e}")

# List of all channel instances
# This will be populated by the MonitorNode or main __init__
ACTIVE_CHANNELS = []

def initialize_channels(ps_instance):
    global prompt_server, ACTIVE_CHANNELS
    set_prompt_server(ps_instance) # Set for PromptServerChannel and any other that might need it
    
    ACTIVE_CHANNELS = []
    
    ps_channel = PromptServerChannel()
    if ps_channel.is_enabled():
        ACTIVE_CHANNELS.append(ps_channel)

    redis_channel = RedisChannel()
    if redis_channel.is_enabled():
        ACTIVE_CHANNELS.append(redis_channel)
    
    rocketmq_channel = RocketMQChannel()
    if rocketmq_channel.is_enabled():
        ACTIVE_CHANNELS.append(rocketmq_channel)
    
    print(f"[KY_Monitor] Initialized {len(ACTIVE_CHANNELS)} active channels.")
    return ACTIVE_CHANNELS, rocketmq_channel # Return rocketmq_channel for explicit shutdown if needed

def broadcast_info(info_data_list):
    if not info_data_list:
        return
    for channel in ACTIVE_CHANNELS:
        try:
            channel.send(info_data_list)
        except Exception as e:
            print(f"[KY_Monitor] Unhandled error during broadcast to {type(channel).__name__}: {e}")
            traceback.print_exc()

if __name__ == '__main__':
    # Mocking for standalone testing
    class MockPromptServer:
        def send_sync(self, event_name, data, sid=None):
            print(f"MockPromptServer: Event '{event_name}' sent with data: {json.dumps(data)}")

    mock_ps_instance = MockPromptServer()
    
    # Test with PromptServerChannel enabled by default in config mock (if not overridden by env)
    # To test Redis/RocketMQ, you'd need actual servers or more complex mocks and set env vars/
    # or a dummy config.json that enables them.
    
    # Example: Temporarily enable Redis for testing (requires Redis server running)
    # APP_CONFIG.redis_enabled = True 
    # APP_CONFIG.redis_host = "localhost" # Ensure this is correct

    # Example: Temporarily enable RocketMQ for testing (requires RocketMQ server running)
    # APP_CONFIG.rocketmq_enabled = True
    # APP_CONFIG.rocketmq_namesrv_addr = "localhost:9876" # Ensure this is correct

    initialized_channels, mq_channel_ref = initialize_channels(mock_ps_instance)
    print(f"Active channels for test: {[type(c).__name__ for c in initialized_channels]}")

    sample_info = [
        {"id": "test_prompt_1", "status": "running", "progress": 0.5},
        {"id": "test_prompt_2", "status": "pending", "queue_position": 1}
    ]
    broadcast_info(sample_info)

    if mq_channel_ref and mq_channel_ref.is_enabled():
        mq_channel_ref.shutdown() # Test shutdown

    print("\nChannel.py mock test completed.")
    print("Note: For Redis/RocketMQ, actual sending requires running servers and installed libraries.")
    print("If Redis/RocketMQ were enabled and libs missing, errors would be printed above.") 
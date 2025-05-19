import logging
from .channel import set_prompt_server, PromptServerChannel, RedisChannel, RocketMQChannel

logger = logging.getLogger("KY_monitor_manager")

# 所有渠道实例列表
ACTIVE_CHANNELS = []

def initialize_channels(ps_instance):
    global ACTIVE_CHANNELS
    set_prompt_server(ps_instance)
    
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
    
    logger.info(f"已初始化 {len(ACTIVE_CHANNELS)} 个活动渠道")
    return ACTIVE_CHANNELS, rocketmq_channel

def broadcast_info(info_data_list):
    if not info_data_list:
        return
    for channel in ACTIVE_CHANNELS:
        try:
            channel.send(info_data_list)
        except Exception as e:
            logger.error(f"广播到 {type(channel).__name__} 时发生未处理的错误: {e}") 
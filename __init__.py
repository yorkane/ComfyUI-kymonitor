# /ComfyUI/custom_nodes/KY_monitor/__init__.py
import logging
import os # 导入 os 模块

# 设置此模块的 logger
logger = logging.getLogger("KY_monitor_init") # 使用特定名称
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 创建格式化器
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)

# 添加处理器到logger
logger.addHandler(console_handler)

# logger.info("[KY_monitor Node] 正在初始化，支持环境变量自动执行...")

# 初始化配置
from .config import APP_CONFIG
logger.info("[KY_monitor Node] 配置管理器已加载")

# 用于延迟初始化，确保 ComfyUI 的核心组件（如事件循环）已准备好
def _deferred_init():
    try:
        from . import monitor_logic
        from .notifications import initialize_channels
        
        # 监控频率（秒）
        monitor_interval = APP_CONFIG.frequency_seconds
        
        # 初始化通知渠道
        channels, rocketmq_channel = initialize_channels(server.PromptServer.instance)
        
        monitor_logic.initialize_monitor(
            monitor_interval_seconds=monitor_interval,
            channels=channels,
            rocketmq_channel=rocketmq_channel
        )
        logger.info(f"[KY_monitor Node] 配置管理器-{APP_CONFIG.prompt_server_event_name}: {APP_CONFIG.prompt_server_enabled}")
        logger.info(f"[KY_monitor Node] 监控初始化完成。间隔: {monitor_interval}秒")

    except Exception as e:
        logger.error(f"[KY_monitor Node] 初始化监控失败: {e}", exc_info=True)

# 检查 PromptServer 实例和它的事件循环是否可用
# ComfyUI 加载 __init__.py 时，这些应该已经存在
try:
    import server
    if hasattr(server, 'PromptServer') and server.PromptServer.instance and server.PromptServer.instance.loop:
        server.PromptServer.instance.loop.call_soon(_deferred_init)
    else:
        logger.error("[KY_monitor Node] 无法调度监控初始化: PromptServer或其循环在导入时未就绪")
except ImportError:
    logger.error("[KY_monitor Node] 导入'server'模块失败。ComfyUI环境可能未正确设置为自定义节点")
except Exception as e:
    logger.error(f"[KY_monitor Node] 设置过程中发生意外错误: {e}", exc_info=True)

# 此自定义节点不再提供UI节点，因此mappings为空或不定义
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
# WEB_DIRECTORY = "js" # 不再需要，因为没有UI交互的JS

logger.info("[KY_monitor Node] 加载完成（无UI节点）。监控将基于环境变量或默认值运行。") 
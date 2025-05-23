# /ComfyUI/custom_nodes/KY_monitor/monitor_logic.py

import asyncio
import math
import threading
import time
import server  # 用于访问 PromptServer.instance
import execution  # 用于访问 PromptQueue (如果需要更底层的队列访问)
import logging  # 使用 logging 模块记录信息
import json  # ADDED
import redis  # ADDED

# from rocketmq.client import Producer, Message # ADDED
import rocketmq_client
from .notifications import broadcast_info
from .config import APP_CONFIG

# 设置一个专用的 logger
logger = logging.getLogger("KY_monitor_logic")  # 使用特定名称
logger.setLevel(logging.INFO)  # 您可以根据需要调整日志级别


class ComfyMonitor:
    def __init__(self, loop, rate=5, channels=None, rocketmq_channel=None):
        self.loop = loop
        self.rate = float(rate)
        self.prompt_server = server.PromptServer.instance
        self._stop_event = asyncio.Event()
        self._completed_prompts_count = {}
        self.channels = channels or []
        self.rocketmq_channel = rocketmq_channel

        self.redis_client = None
        self.rocketmq_producer = None
        self.rocketmq_topic = None
        self.rocketmq_namesrv_addr = None
        self.redis_host = None

        if not self.prompt_server:
            logger.error("PromptServer.instance在初始化时不可用")
        if not self.loop:
            logger.error("asyncio loop在初始化时不可用")

        # 处理 channels 参数
        if channels:
            if isinstance(channels, dict):
                channel_config = channels
            elif isinstance(channels, list) and len(channels) > 0:
                channel_config = channels[0]  # 使用第一个配置
            else:
                channel_config = None

            if channel_config and isinstance(channel_config, dict):
                try:
                    self.redis_host = channel_config.get("host")
                    if self.redis_host and channel_config.get("port"):
                        self.redis_client = redis.StrictRedis(
                            host=channel_config["host"],
                            port=channel_config["port"],
                            db=channel_config.get("db", 0),
                            password=channel_config.get("password"),
                            decode_responses=True,
                            socket_connect_timeout=5,
                        )
                        self.redis_client.ping()
                        logger.info(
                            f"[KY_monitor] Redis client initialized and connected to {channel_config['host']}:{channel_config['port']}."
                        )
                except Exception as e:
                    logger.error(
                        f"[KY_monitor] Failed to initialize Redis client for {channel_config.get('host')}:{channel_config.get('port')}: {e}"
                    )
                    self.redis_client = None

        # 处理 rocketmq_channel 参数
        if rocketmq_channel:
            try:
                # 如果 rocketmq_channel 是对象，尝试直接访问属性
                if hasattr(rocketmq_channel, "namesrv_addr") and hasattr(
                    rocketmq_channel, "topic"
                ):
                    self.rocketmq_namesrv_addr = rocketmq_channel.namesrv_addr
                    self.rocketmq_topic = rocketmq_channel.topic
                    group_id = getattr(
                        rocketmq_channel, "group_id", "KY_MONITOR_PRODUCER_GROUP"
                    )
                # 如果 rocketmq_channel 是字典，使用 get 方法
                elif isinstance(rocketmq_channel, dict):
                    self.rocketmq_namesrv_addr = rocketmq_channel.get("namesrv_addr")
                    self.rocketmq_topic = rocketmq_channel.get("topic")
                    group_id = rocketmq_channel.get(
                        "group_id", "KY_MONITOR_PRODUCER_GROUP"
                    )
                else:
                    logger.error(
                        f"[KY_monitor] Invalid rocketmq_channel format: {type(rocketmq_channel)}"
                    )
                    return

                if self.rocketmq_namesrv_addr and self.rocketmq_topic:
                    self.rocketmq_producer = rocketmq_client.Producer(group_id)
                    self.rocketmq_producer.set_namesrv_addr(self.rocketmq_namesrv_addr)
                    self.rocketmq_producer.start()
                    logger.info(
                        f"[KY_monitor] RocketMQ producer initialized and started. Nameserver: {self.rocketmq_namesrv_addr}, Topic: {self.rocketmq_topic}, Group: {group_id}"
                    )
            except Exception as e:
                logger.error(
                    f"[KY_monitor] Failed to initialize RocketMQ producer: {e}"
                )
                self.rocketmq_producer = None

    async def send_message(self, event_name: str, data: dict) -> None:
        """通过所有可用的通知渠道发送消息"""
        # 通过所有渠道发送消息
        broadcast_info(
            [{"event": event_name or APP_CONFIG.prompt_server_event_name, "data": data}]
        )

    def get_queue_status(self) -> dict:
        """获取当前队列状态"""
        if not (
            self.prompt_server
            and hasattr(self.prompt_server, "prompt_queue")
            and self.prompt_server.prompt_queue
        ):
            return {"error": "队列不可用"}

        queue = self.prompt_server.prompt_queue
        server_last_node_id = self.prompt_server.last_node_id

        current_queue_snapshot = queue.get_current_queue()
        all_prompts_info = []

        running_queue_items = current_queue_snapshot[0]
        # logger.info(f"running_queue_items: {running_queue_items}")
        pending_queue_items = current_queue_snapshot[1]
        # logger.info(f"pending_queue_items: {pending_queue_items}")

        # 处理正在运行的队列
        for idx, item_tuple in enumerate(running_queue_items):
            prompt_id_val = item_tuple[1]
            position_val = item_tuple[0]
            client_id_val = None
            extra_data_val = item_tuple[3] if len(item_tuple) > 3 else None
            if isinstance(extra_data_val, dict):
                client_id_val = extra_data_val.get("client_id")

            task_info = {
                "prompt_id": prompt_id_val,
                "position": position_val,
                "client_id": client_id_val,
                "status": "running",
            }

            if idx == 0:  # 假设第一个是当前主要活动的工作流
                total_nodes_in_workflow = 0
                current_executing_node_order = 0
                nodes_completed_count = 0
                progress_percentage = 0
                current_node_name = None

                workflow_nodes_list = []
                try:
                    if (
                        isinstance(extra_data_val, dict)
                        and "extra_pnginfo" in extra_data_val
                        and isinstance(extra_data_val["extra_pnginfo"], dict)
                        and "workflow" in extra_data_val["extra_pnginfo"]
                        and isinstance(
                            extra_data_val["extra_pnginfo"]["workflow"], dict
                        )
                        and "nodes" in extra_data_val["extra_pnginfo"]["workflow"]
                        and isinstance(
                            extra_data_val["extra_pnginfo"]["workflow"]["nodes"], list
                        )
                    ):

                        valid_nodes_for_ordering = []
                        for node_data in extra_data_val["extra_pnginfo"]["workflow"][
                            "nodes"
                        ]:
                            if (
                                isinstance(node_data, dict)
                                and "order" in node_data
                                and "id" in node_data
                            ):
                                valid_nodes_for_ordering.append(node_data)
                            else:
                                logger.debug(
                                    f"节点数据缺少'order'或'id', prompt {prompt_id_val}: {node_data}"
                                )

                        workflow_nodes_list = sorted(
                            valid_nodes_for_ordering, key=lambda n: n["order"]
                        )
                        total_nodes_in_workflow = len(workflow_nodes_list)

                        if server_last_node_id and total_nodes_in_workflow > 0:
                            for i, node in enumerate(workflow_nodes_list):
                                if str(node["id"]) == str(server_last_node_id):
                                    current_executing_node_order = i + 1
                                    nodes_completed_count = i
                                    current_node_name = node.get("type", "Unknown")
                                    break
                            if current_executing_node_order > 0:
                                progress_percentage = math.ceil(
                                    (
                                        current_executing_node_order
                                        * 100
                                        / total_nodes_in_workflow
                                    )
                                )

                except Exception as e:
                    logger.error(
                        f"处理工作流节点失败，prompt {prompt_id_val}: {e}",
                        exc_info=True,
                    )

                task_info["progress"] = {
                    "total_nodes": total_nodes_in_workflow,
                    "current_node_id": server_last_node_id,
                    "current_node_name": current_node_name,
                    "node_order": current_executing_node_order,
                    "completed_count": nodes_completed_count,
                    "percentage": round(progress_percentage, 2),
                }

            all_prompts_info.append(task_info)

        # 处理等待队列
        for item_tuple in pending_queue_items:
            prompt_id_val = item_tuple[1]
            position_val = item_tuple[0]
            client_id_val = None
            extra_data_val = item_tuple[3] if len(item_tuple) > 3 else None
            if isinstance(extra_data_val, dict):
                client_id_val = extra_data_val.get("client_id")

            all_prompts_info.append(
                {
                    "prompt_id": prompt_id_val,
                    "position": position_val,
                    "client_id": client_id_val,
                    "status": "waiting",
                }
            )

        # 处理已完成的任务
        if queue.history:
            # logger.info(f"queue.history: {queue.history}") ==
            # 获得最新的5个
            latest_history_items = list(queue.history.items())[-5:]

            for prompt_id_str, history_item in list(latest_history_items):
                current_send_count = self._completed_prompts_count.get(prompt_id_str, 0)
                # 只发送一次成功/错误
                if current_send_count >= 1:
                    continue
                else:
                    self._completed_prompts_count[prompt_id_str] = (
                        current_send_count + 1
                    )
                status_dict = history_item.get("status")
                if not status_dict:
                    continue
                status_str = status_dict.get("status_str", "")
                is_success = status_str == "success"
                is_error = status_str == "error"
                info = {}
                if is_error:
                    for msg_type, msg_data in status_dict.get("messages", []):
                        if msg_type == "execution_error":
                            info = {
                                # execution_start 不在 execution_error 消息中，移除
                                "error_node_id": msg_data.get("node_id"),
                                "error_node_type": msg_data.get("node_type"),
                                "error_message": msg_data.get("exception_type")
                                + ": "
                                + msg_data.get("exception_message"),
                                # "error_type": msg_data.get('exception_type'),
                                # 只获取 traceback 列表的前2个
                                "traceback": msg_data.get("traceback", [])[
                                    :2
                                ],  # 获取 traceback 列表
                                "timestamp": msg_data.get("timestamp"),
                                # "executed_nodes_before_error": msg_data.get('executed', []),
                                # "failing_node_inputs": msg_data.get('current_inputs', {}),
                                # "expected_node_outputs": msg_data.get('current_outputs', [])
                            }
                            break  # 找到 execution_error 消息后即可跳出
                        # logger.info(f"error_details_found: {error_details_found}")
                elif is_success:
                    info = {
                        "prompt_id": prompt_id_str,
                        "status": status_str,
                        "outputs": history_item.get('outputs', {}),
                        "messages": status_dict.get('messages', []),
                        "prompts":  history_item.get('prompt', []),
                    }
                else:
                    if prompt_id_str in self._completed_prompts_count:
                        logger.warning(
                            f"Prompt {prompt_id_str} 从历史记录中，之前追踪完成/错误，不再处于最终状态。状态: {status_dict}。从发送追踪中移除。"
                        )
                        del self._completed_prompts_count[prompt_id_str]
                    continue

                all_prompts_info.append(
                    {
                        "prompt_id": prompt_id_str,
                        "status": status_str,
                        "info": info,
                    }
                )

        return {
            "queue_status": {
                "running": len(queue.currently_running),
                "waiting": len(queue.queue),
                "completed": queue.task_counter,
            },
            "prompts": all_prompts_info,
        }

    async def monitor_loop(self):
        """监控循环"""
        while not self._stop_event.is_set():
            try:
                queue_status = self.get_queue_status()
                # 检查队列是否为空
                if len(queue_status["prompts"]) > 0:
                    # logger.info(                        f"Kmonitor: {APP_CONFIG.prompt_server_event_name}:\n{queue_status}"  )
                    await self.send_message("ky_monitor.queue", queue_status)
                else:
                    logger.debug("队列为空，跳过消息发送")

            except Exception as e:
                logger.error(f"监控循环中发生错误: {e}", exc_info=True)

            await asyncio.sleep(self.rate)

    def start(self):
        """启动监控"""
        if not self.loop:
            logger.error("无法启动监控：没有可用的asyncio loop")
            return

        self._stop_event.clear()
        self.loop.create_task(self.monitor_loop())
        logger.info(f"监控已启动，间隔: {self.rate}秒")

    def stop(self):
        """停止监控"""
        self._stop_event.set()
        if self.rocketmq_channel:
            self.rocketmq_channel.shutdown()
        logger.info("监控已停止")


monitor_instance = None


def initialize_monitor(
    monitor_interval_seconds=5, channels=None, rocketmq_channel=None
):
    """初始化监控器"""
    try:
        if not server.PromptServer.instance or not server.PromptServer.instance.loop:
            logger.error("无法初始化监控：PromptServer或loop不可用")
            return None

        monitor = ComfyMonitor(
            loop=server.PromptServer.instance.loop,
            rate=monitor_interval_seconds,
            channels=channels,
            rocketmq_channel=rocketmq_channel,
        )
        monitor.start()
        return monitor
    except Exception as e:
        logger.error(f"初始化监控失败: {e}", exc_info=True)
        return None


def shutdown_monitor():
    """关闭监控器"""
    global monitor_instance
    if monitor_instance:
        logger.info("[KY_monitor] Shutting down monitor.")
        monitor_instance.stop()
        monitor_instance = None
    else:
        logger.info("[KY_monitor] Monitor not running or already shut down.")

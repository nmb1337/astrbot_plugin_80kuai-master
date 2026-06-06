"""
astrbot_plugin_group_welcome —— 群聊入群欢迎插件

功能：
  - 监听 QQ 群「新成员加群」事件（OneBot v11 / aiocqhttp）
  - 通过临时会话向新成员依次发送：
      1. 群聊卡片（推荐加群 / 群名片）
      2. 聊天记录（QQ 合并转发消息）
      3. 图片（自定义 URL 或本地路径）
  - 支持群白名单：仅白名单内的群触发欢迎
  - 所有内容均可通过 WebUI 配置 (_conf_schema.json)
"""

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.api.message_components import Node, Nodes, Plain, Image, Contact


@register(
    "astrbot_plugin_group_welcome",
    "YourName",
    "新成员加群时通过临时会话推送群聊卡片、合并转发聊天记录和图片，支持群白名单。",
    "1.0.0",
)
class GroupWelcomePlugin(Star):
    """入群欢迎插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    async def initialize(self):
        """插件初始化（可选）"""
        logger.info("GroupWelcomePlugin 已初始化")

    # ── 监听所有 aiocqhttp 事件，过滤 group_increase 通知 ──────────────
    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_notice_group_increase(self, event: AstrMessageEvent):
        """当收到群成员增加通知时触发欢迎流程"""
        # 1. 检查是否启用
        if not self.config.get("enable", True):
            return

        # 2. 确认是群成员增加通知
        raw = event.message_obj.raw_message
        notice_type = raw.get("notice_type", "")
        if notice_type != "group_increase":
            return

        # 3. 获取群号和新人 QQ
        group_id = str(raw.get("group_id", ""))
        user_id = str(raw.get("user_id", ""))
        if not group_id or not user_id:
            logger.warning("[GroupWelcome] 无法获取 group_id 或 user_id，跳过")
            return

        # 4. 白名单检查
        whitelist = self.config.get("whitelist", [])
        # 统一转为字符串比较
        whitelist_str = [str(g) for g in whitelist]
        if whitelist_str and group_id not in whitelist_str:
            logger.info(f"[GroupWelcome] 群 {group_id} 不在白名单中，跳过")
            return

        logger.info(f"[GroupWelcome] 检测到新成员 {user_id} 加入群 {group_id}")

        # 5. 获取 bot 客户端（aiocqhttp 专用）
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )

        if not isinstance(event, AiocqhttpMessageEvent):
            logger.warning("[GroupWelcome] 非 aiocqhttp 事件，跳过")
            return
        bot = event.bot

        # 6. 读取欢迎配置
        wc = self.config.get("welcome_config", {})

        # ── 6a. 发送群聊卡片 ─────────────────────────────────────────
        if wc.get("send_card", True):
            await self._send_group_card(bot, user_id, group_id, wc)

        # ── 6b. 发送合并转发聊天记录 ─────────────────────────────────
        if wc.get("send_forward", True):
            await self._send_forward_nodes(bot, user_id, group_id, wc)

        # ── 6c. 发送图片 ─────────────────────────────────────────────
        if wc.get("send_image", True):
            await self._send_welcome_image(bot, user_id, group_id, wc)

        # 停止事件传播，避免后续 pipeline 处理此通知事件
        event.stop_event()

    # ── 辅助方法 ──────────────────────────────────────────────────────

    async def _send_group_card(self, bot, user_id: str, group_id: str, wc: dict):
        """通过临时会话发送群聊卡片（推荐加群）"""
        try:
            card_group_id = wc.get("card_group_id", "") or group_id
            contact_msg = [
                {
                    "type": "contact",
                    "data": {
                        "type": "group",  # 推荐群
                        "id": str(card_group_id),
                    },
                }
            ]
            ret = await bot.call_action(
                "send_private_msg",
                user_id=user_id,
                group_id=group_id,  # 临时会话需要带上 group_id
                message=contact_msg,
            )
            logger.info(f"[GroupWelcome] 群聊卡片已发送 -> {user_id}, ret={ret}")
        except Exception as e:
            logger.error(f"[GroupWelcome] 发送群聊卡片失败: {e}")

    async def _send_forward_nodes(self, bot, user_id: str, group_id: str, wc: dict):
        """通过临时会话发送合并转发聊天记录"""
        try:
            forward_cfgs = wc.get("forward_nodes", [])
            if not forward_cfgs:
                logger.info("[GroupWelcome] 未配置 forward_nodes，跳过合并转发")
                return

            nodes = []
            for node_cfg in forward_cfgs:
                content = []
                for item in node_cfg.get("content", []):
                    t = item.get("type", "plain")
                    if t == "plain":
                        content.append(Plain(text=item.get("text", "")))
                    elif t == "image":
                        src = item.get("file", "") or item.get("url", "")
                        if src.startswith("http"):
                            content.append(Image.fromURL(src))
                        elif src:
                            content.append(Image.fromFileSystem(src))
                node = Node(
                    uin=str(node_cfg.get("uin", "0")),
                    name=node_cfg.get("name", ""),
                    content=content,
                )
                nodes.append(node)

            if nodes:
                nodes_obj = Nodes(nodes=nodes)
                messages = (await nodes_obj.to_dict())["messages"]
                # 尝试附加 group_id 以支持临时会话场景
                try:
                    await bot.call_action(
                        "send_private_forward_msg",
                        user_id=user_id,
                        group_id=group_id,
                        messages=messages,
                    )
                except Exception:
                    # 部分协议端可能不支持 group_id 参数，回退无 group_id
                    await bot.call_action(
                        "send_private_forward_msg",
                        user_id=user_id,
                        messages=messages,
                    )
                logger.info(f"[GroupWelcome] 合并转发消息已发送 -> {user_id}")
        except Exception as e:
            logger.error(f"[GroupWelcome] 发送合并转发消息失败: {e}")

    async def _send_welcome_image(self, bot, user_id: str, group_id: str, wc: dict):
        """通过临时会话发送图片"""
        try:
            image_url = wc.get("image_url", "")
            if not image_url:
                return

            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                AiocqhttpMessageEvent,
            )

            if image_url.startswith("http"):
                img = Image.fromURL(image_url)
            else:
                img = Image.fromFileSystem(image_url)
            img_dict = await AiocqhttpMessageEvent._from_segment_to_dict(img)
            await bot.call_action(
                "send_private_msg",
                user_id=user_id,
                group_id=group_id,
                message=[img_dict],
            )
            logger.info(f"[GroupWelcome] 欢迎图片已发送 -> {user_id}")
        except Exception as e:
            logger.error(f"[GroupWelcome] 发送欢迎图片失败: {e}")

    async def terminate(self):
        """插件卸载时调用（可选）"""
        logger.info("GroupWelcomePlugin 已卸载")


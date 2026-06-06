"""
astrbot_plugin_group_welcome —— 群聊入群欢迎插件

功能：
  - 监听 QQ 群「新成员加群」事件（OneBot v11 / aiocqhttp）
  - 通过临时会话向新成员依次发送：
      1. 群聊卡片（推荐加群 / 群名片）
      2. 聊天记录（QQ 合并转发消息）
      3. 图片（自定义 URL 或本地路径）
  - 支持群白名单：仅白名单内的群触发欢迎
  - 通过 /welcome 指令设置欢迎内容
"""

import copy
import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig


# ── 原始数据转换：get_forward_msg 响应 → send_forward_msg 请求格式 ────

def _convert_raw_to_send_format(messages: list) -> list:
    """将 get_forward_msg 返回的原始 messages 转为 send_forward_msg 格式。
    纯 dict 操作，不依赖 AstrBot/Pydantic，递归处理嵌套 forward。
    """
    result = []
    for msg in messages:
        sender = msg.get("sender", {})
        raw_content = msg.get("message") or msg.get("content") or []
        node = {
            "type": "node",
            "data": {
                "user_id": str(sender.get("user_id", "0")),
                "nickname": sender.get("nickname", ""),
                "content": _convert_content_segments(raw_content),
            },
        }
        result.append(node)
    return result


def _convert_content_segments(segments: list) -> list:
    """递归转换内容段列表，将嵌套 forward 展开为 node 段。"""
    out = []
    for seg in segments:
        t = seg.get("type", "")
        if t == "forward":
            inline = seg.get("data", {}).get("content") or []
            if inline:
                out.extend(_convert_raw_to_send_format(inline))
        elif t == "node":
            data = seg.get("data", {})
            out.append({
                "type": "node",
                "data": {
                    "user_id": str(data.get("user_id", "0")),
                    "nickname": data.get("nickname", ""),
                    "content": _convert_content_segments(data.get("content") or []),
                },
            })
        elif t in ("image", "video", "record"):
            d = dict(seg.get("data", {}))
            url = d.get("url", "")
            if url and url.startswith("http"):
                d["file"] = url
            out.append({"type": t, "data": d})
        else:
            # text / face / at / markdown / reply 等直接保留
            logger.debug(f"[GroupWelcome] convert passthrough segment type={t}")
            out.append(copy.deepcopy(seg))
    return out


# ── 插件主体 ──────────────────────────────────────────────────────────

@register(
    "astrbot_plugin_group_welcome",
    "YourName",
    "新成员加群时临时会话推送群聊卡片、合并转发聊天记录和图片，支持群白名单。",
    "1.2.0",
)
class GroupWelcomePlugin(Star):

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    async def initialize(self):
        logger.info("GroupWelcomePlugin 已初始化")

    # ── 指令 ──────────────────────────────────────────────────────

    @filter.command_group("welcome")
    def welcome(self):
        pass

    @welcome.command("set_forward")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_set_forward(self, event: AstrMessageEvent):
        yield event.plain_result("🔍 正在解析合并转发消息，请稍候...")
        raw_msgs = await self._fetch_raw_forward(event)
        if not raw_msgs:
            msgs = event.get_messages()
            detail = "\n".join(f"  [{i}] {type(c).__name__}" for i, c in enumerate(msgs)) or "  （消息链为空）"
            yield event.plain_result(
                f"❌ 未找到合并转发消息。\n\n当前消息包含的组件类型：\n{detail}\n\n"
                f"请确保：\n1. 先发送一条 QQ「合并转发」消息到群里\n"
                f"2. 长按那条消息 → 选择「引用」（回复）\n3. 输入 /welcome set_forward 发送"
            )
            return
        wc = self.config.get("welcome_config", {})
        wc["raw_messages"] = raw_msgs
        wc["send_forward"] = True
        self.config["welcome_config"] = wc
        self.config.save_config()
        send_count = len(_convert_raw_to_send_format(raw_msgs))
        yield event.plain_result(f"✅ 已捕获合并转发（{send_count} 条消息），新成员加群时将自动发送。")

    @welcome.command("set_card")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_set_card(self, event: AstrMessageEvent, group_id: str = ""):
        wc = self.config.get("welcome_config", {})
        wc["card_group_id"] = str(group_id or event.get_group_id() or "")
        wc["send_card"] = True
        self.config["welcome_config"] = wc
        self.config.save_config()
        yield event.plain_result(f"✅ 群聊卡片目标群号已设置为：{wc['card_group_id']}")

    @welcome.command("set_image")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_set_image(self, event: AstrMessageEvent, url: str = ""):
        wc = self.config.get("welcome_config", {})
        if not url:
            for comp in event.get_messages():
                if isinstance(comp, Comp.Image):
                    url = getattr(comp, "url", "") or getattr(comp, "file", "") or ""
                    break
        if not url:
            yield event.plain_result("❌ 请提供图片 URL 或路径")
            return
        wc["image_url"] = url
        wc["send_image"] = True
        self.config["welcome_config"] = wc
        self.config.save_config()
        yield event.plain_result(f"✅ 欢迎图片已设置为：{url}")

    @welcome.command("show")
    async def cmd_show(self, event: AstrMessageEvent):
        wc = self.config.get("welcome_config", {})
        whitelist = self.config.get("whitelist", [])
        enabled = self.config.get("enable", True)
        raw_count = len(wc.get("raw_messages", []))
        send_count = len(_convert_raw_to_send_format(wc.get("raw_messages", [])))
        lines = [
            f"🔧 状态：{'🟢 已启用' if enabled else '🔴 已禁用'}",
            f"🛡️ 白名单：{whitelist if whitelist else '（空=所有群生效）'}",
            f"🃏 群聊卡片：{'✅' if wc.get('send_card') else '❌'} 目标群={wc.get('card_group_id', '当前群')}",
            f"📨 合并转发：{'✅' if wc.get('send_forward') else '❌'} 原始 {raw_count} 条 / 发送 {send_count} 条",
            f"🖼️ 欢迎图片：{'✅' if wc.get('send_image') else '❌'} {wc.get('image_url', '未设置')[:60]}",
        ]
        yield event.plain_result("\n".join(lines))

    @welcome.command("clear")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_clear(self, event: AstrMessageEvent):
        self.config["welcome_config"] = {}
        self.config.save_config()
        yield event.plain_result("✅ 已清除所有欢迎内容（白名单不变）。")

    # ── 加群事件 ──────────────────────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_notice_group_increase(self, event: AstrMessageEvent):
        if not self.config.get("enable", True):
            return
        raw = event.message_obj.raw_message
        if raw.get("notice_type", "") != "group_increase":
            return
        group_id = str(raw.get("group_id", ""))
        user_id = str(raw.get("user_id", ""))
        if not group_id or not user_id:
            return
        whitelist = [str(g) for g in self.config.get("whitelist", [])]
        if whitelist and group_id not in whitelist:
            return
        logger.info(f"[GroupWelcome] 新成员 {user_id} 加入群 {group_id}")

        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        if not isinstance(event, AiocqhttpMessageEvent):
            return
        bot = event.bot
        wc = self.config.get("welcome_config", {})
        if wc.get("send_card", True):
            await self._send_group_card(bot, user_id, group_id, wc)
        if wc.get("send_forward", True):
            await self._send_stored_forward(bot, user_id, group_id, wc)
        if wc.get("send_image", True):
            await self._send_welcome_image(bot, user_id, group_id, wc)
        event.stop_event()

    # ── 数据获取 ──────────────────────────────────────────────────

    async def _fetch_raw_forward(self, event: AstrMessageEvent) -> list | None:
        """从 Reply/当前消息中提取合并转发，返回 get_forward_msg 原始 messages 数组"""
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        bot = event.bot if isinstance(event, AiocqhttpMessageEvent) else None
        if not bot:
            return None
        msgs = event.get_messages()
        logger.info(f"[GroupWelcome] 消息链: {[type(c).__name__ for c in msgs]}")

        for comp in msgs:
            if not isinstance(comp, Comp.Reply):
                continue
            logger.info(f"[GroupWelcome] Reply id={comp.id} chain_len={len(comp.chain) if comp.chain else 0}")
            if comp.chain:
                for c in comp.chain:
                    if isinstance(c, Comp.Forward) and c.id:
                        raw = await self._get_raw_forward(bot, str(c.id))
                        if raw:
                            return raw
            if comp.id and bot:
                try:
                    ret = await bot.call_action("get_msg", message_id=int(comp.id))
                    if ret and "message" in ret:
                        rmsg = ret["message"]
                        segs = rmsg if isinstance(rmsg, list) else [rmsg]
                        for seg in segs:
                            if seg.get("type") == "forward":
                                fid = seg.get("data", {}).get("id", "")
                                if fid:
                                    raw = await self._get_raw_forward(bot, str(fid))
                                    if raw:
                                        return raw
                except Exception as e:
                    logger.error(f"[GroupWelcome] get_msg 失败: {e}")
        for comp in msgs:
            if isinstance(comp, Comp.Forward) and comp.id:
                raw = await self._get_raw_forward(bot, str(comp.id))
                if raw:
                    return raw
        return None

    async def _get_raw_forward(self, bot, forward_id: str) -> list | None:
        try:
            logger.info(f"[GroupWelcome] get_forward_msg id={forward_id}")
            ret = await bot.call_action("get_forward_msg", message_id=forward_id)
            if ret and "messages" in ret:
                logger.info(f"[GroupWelcome] 获取到 {len(ret['messages'])} 条原始消息")
                return ret["messages"]
        except Exception as e:
            logger.error(f"[GroupWelcome] get_forward_msg 失败: {e}")
        return None

    # ── 发送 ──────────────────────────────────────────────────────

    async def _send_stored_forward(self, bot, user_id: str, group_id: str, wc: dict):
        raw_msgs = wc.get("raw_messages", [])
        if not raw_msgs:
            return
        try:
            messages = _convert_raw_to_send_format(raw_msgs)
            logger.info(f"[GroupWelcome] 准备发送 {len(messages)} 条消息")
            try:
                await bot.call_action("send_private_forward_msg", user_id=user_id, group_id=group_id, messages=messages)
            except Exception as e1:
                logger.warning(f"[GroupWelcome] 带 group_id 发送失败: {e1}")
                # 尝试不带 group_id
                await bot.call_action("send_private_forward_msg", user_id=user_id, messages=messages)
            logger.info(f"[GroupWelcome] 合并转发已发送 -> {user_id}")
        except Exception as e:
            # 捕获 ActionFailed 的详细信息
            extra = ""
            if hasattr(e, 'result'):
                extra = f" | NapCat result: {e.result}"
            import traceback
            logger.error(f"[GroupWelcome] 发送合并转发失败: {e}{extra}\n{traceback.format_exc()}")

    async def _send_group_card(self, bot, user_id: str, group_id: str, wc: dict):
        try:
            card_group_id = wc.get("card_group_id", "") or group_id
            await bot.call_action("send_private_msg", user_id=user_id, group_id=group_id, message=[{
                "type": "contact", "data": {"type": "group", "id": str(card_group_id)},
            }])
        except Exception as e:
            logger.error(f"[GroupWelcome] 发送群聊卡片失败: {e}")

    async def _send_welcome_image(self, bot, user_id: str, group_id: str, wc: dict):
        try:
            image_url = wc.get("image_url", "")
            if not image_url:
                return
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
            img = Comp.Image.fromURL(image_url) if image_url.startswith("http") else Comp.Image.fromFileSystem(image_url)
            img_dict = await AiocqhttpMessageEvent._from_segment_to_dict(img)
            await bot.call_action("send_private_msg", user_id=user_id, group_id=group_id, message=[img_dict])
        except Exception as e:
            logger.error(f"[GroupWelcome] 发送欢迎图片失败: {e}")

    async def terminate(self):
        logger.info("GroupWelcomePlugin 已卸载")


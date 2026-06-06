"""
astrbot_plugin_group_welcome —— 群聊入群欢迎插件

功能：
  - 监听 QQ 群「新成员加群」事件（OneBot v11 / aiocqhttp）
  - 通过临时会话向新成员依次发送：
      1. 群聊卡片（推荐加群 / 群名片）
      2. 聊天记录（QQ 合并转发消息，可发送一条已有的合并转发让机器人捕获）
      3. 图片（自定义 URL 或本地路径）
  - 支持群白名单：仅白名单内的群触发欢迎
  - 通过 /welcome 指令设置欢迎内容

用法：
  1. 先发送一条 QQ 合并转发消息到群里
  2. 引用（回复）那条消息，发送 /welcome set_forward
  3. 机器人会捕获该合并转发并保存
  4. 之后新成员加群时自动转发该聊天记录（通过临时会话）
"""

import astrbot.api.message_components as Comp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig


# ── 原始 forward 段包装器：完整保留 NapCat data 结构 ────────────────

class _RawForward:
    """保存 NapCat get_forward_msg 返回的原始 forward 段 data。
    调用 toDict() 时输出 {"type":"forward","data":{...}}，
    Node.to_dict() 的 else 分支会自动将其落入父级 content 数组，
    从而完整保留嵌套转发卡片。
    """
    def __init__(self, data: dict):
        self._data = data

    def toDict(self) -> dict:
        return {"type": "forward", "data": self._data}


# ── 序列化 / 反序列化工具 ─────────────────────────────────────────────

def _serialize_component(comp) -> dict | None:
    """将单个消息组件序列化为可 JSON 存储的 dict（支持递归嵌套 Node/Nodes）"""
    if isinstance(comp, Comp.Plain):
        return {"type": "plain", "text": comp.text or ""}
    if isinstance(comp, Comp.Image):
        url = getattr(comp, "url", None)
        file = getattr(comp, "file", None)
        path = getattr(comp, "path", None)
        src = url or file or path or ""
        if src:
            if isinstance(src, str) and src.startswith("http"):
                return {"type": "image", "url": src}
            return {"type": "image", "file": str(src)}
        return None
    if isinstance(comp, Comp.Face):
        return {"type": "face", "id": getattr(comp, "id", 0)}
    if isinstance(comp, Comp.At):
        return {"type": "at", "qq": str(getattr(comp, "qq", ""))}
    if isinstance(comp, _RawForward):
        # 完整保留原始 forward 段 data（不解构，不递归）
        return {"type": "forward", "data": comp._data}
    if isinstance(comp, Comp.Node):
        # 递归：嵌套的合并转发节点保留原结构
        return _serialize_node(comp)
    if isinstance(comp, Comp.Nodes):
        # 递归：嵌套的合并转发消息组
        return {
            "type": "nodes",
            "nodes": [_serialize_node(n) for n in comp.nodes],
        }
    if isinstance(comp, Comp.Forward):
        return {"type": "forward_ref", "id": str(getattr(comp, "id", ""))}
    return {"type": "plain", "text": f"[{type(comp).__name__}]"}


def _deserialize_component(data: dict) -> Comp.BaseMessageComponent:
    """从存储的 dict 还原消息组件（支持递归嵌套 Node/Nodes）"""
    t = data.get("type", "plain")
    if t == "plain":
        return Comp.Plain(text=data.get("text", ""))
    if t == "image":
        url = data.get("url", "")
        if url:
            return Comp.Image.fromURL(url)
        file = data.get("file", "")
        if file:
            return Comp.Image.fromFileSystem(file)
        return Comp.Plain(text="[图片]")
    if t == "face":
        return Comp.Face(id=data.get("id", 0))
    if t == "at":
        return Comp.At(qq=data.get("qq", ""))
    if t == "forward":
        # 完整还原原始 forward 段（不解构，保留原生嵌套卡片）
        return _RawForward(data.get("data", {}))
    if t == "node":
        # 递归：还原嵌套的合并转发节点
        return _deserialize_node(data)
    if t == "nodes":
        # 递归：还原嵌套的合并转发消息组
        nodes = [_deserialize_node(n) for n in data.get("nodes", [])]
        return Comp.Nodes(nodes=nodes)
    if t == "forward_ref":
        return Comp.Plain(text="[聊天记录]")
    return Comp.Plain(text=data.get("text", "[未知消息]"))


def _serialize_node(node: Comp.Node) -> dict:
    """将 Node 序列化为可存储的 dict"""
    content = []
    for c in (node.content or []):
        s = _serialize_component(c)
        if s:
            content.append(s)
    return {
        "uin": str(node.uin or "0"),
        "name": node.name or "",
        "content": content,
    }


def _deserialize_node(data: dict) -> Comp.Node:
    """从存储的 dict 还原 Node"""
    content = [_deserialize_component(c) for c in data.get("content", [])]
    return Comp.Node(
        uin=str(data.get("uin", "0")),
        name=data.get("name", ""),
        content=content,
    )


# ── 插件主体 ──────────────────────────────────────────────────────────

@register(
    "astrbot_plugin_group_welcome",
    "YourName",
    "新成员加群时临时会话推送群聊卡片、合并转发聊天记录和图片，支持群白名单。",
    "1.1.0",
)
class GroupWelcomePlugin(Star):
    """入群欢迎插件"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    async def initialize(self):
        logger.info("GroupWelcomePlugin 已初始化")

    # ══════════════════════════════════════════════════════════════════
    # 指令：/welcome set_forward / set_card / set_image / show / clear
    # ══════════════════════════════════════════════════════════════════

    @filter.command_group("welcome")
    def welcome(self):
        """入群欢迎设置指令组"""
        pass

    @welcome.command("set_forward")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_set_forward(self, event: AstrMessageEvent):
        """捕获引用消息中的合并转发聊天记录并保存"""
        # 先给用户一个反馈，避免长时间等待
        yield event.plain_result("🔍 正在解析合并转发消息，请稍候...")

        nodes = await self._extract_forward_nodes(event)
        if not nodes:
            # 输出诊断信息帮助用户排查
            msgs = event.get_messages()
            detail = "\n".join(
                f"  [{i}] {type(c).__name__}" for i, c in enumerate(msgs)
            ) or "  （消息链为空）"
            yield event.plain_result(
                f"❌ 未找到合并转发消息。\n\n"
                f"当前消息包含的组件类型：\n{detail}\n\n"
                f"请确保：\n"
                f"1. 先发送一条 QQ「合并转发」消息到群里\n"
                f"2. 长按那条消息 → 选择「引用」（回复）\n"
                f"3. 输入 /welcome set_forward 发送\n\n"
                f"💡 也可以直接发送 /welcome set_forward 并引用包含合并转发的消息。"
            )
            return

        # 递归展开嵌套的合并转发，将所有层级消息平铺为单层
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )
        bot = event.bot if isinstance(event, AiocqhttpMessageEvent) else None
        stored = [_serialize_node(n) for n in nodes]
        wc = self.config.get("welcome_config", {})
        wc["forward_nodes"] = stored
        self.config["welcome_config"] = wc
        self.config.save_config()

        yield event.plain_result(
            f"✅ 已捕获 {len(stored)} 条转发消息节点，新成员加群时将自动发送此聊天记录。"
        )

    @welcome.command("set_card")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_set_card(self, event: AstrMessageEvent, group_id: str = ""):
        """设置群聊卡片推荐的目标群号。用法：/welcome set_card 123456789"""
        wc = self.config.get("welcome_config", {})
        if not group_id:
            # 不带参数则使用当前群
            group_id = event.get_group_id() or ""
        wc["card_group_id"] = str(group_id)
        wc["send_card"] = True
        self.config["welcome_config"] = wc
        self.config.save_config()
        yield event.plain_result(f"✅ 群聊卡片目标群号已设置为：{group_id}")

    @welcome.command("set_image")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_set_image(self, event: AstrMessageEvent, url: str = ""):
        """设置欢迎图片。用法：/welcome set_image https://example.com/img.png"""
        wc = self.config.get("welcome_config", {})
        if not url:
            # 尝试从当前消息中提取图片
            for comp in event.get_messages():
                if isinstance(comp, Comp.Image):
                    url = getattr(comp, "url", "") or getattr(comp, "file", "") or ""
                    break
        if not url:
            yield event.plain_result("❌ 请提供图片 URL 或路径，例如 /welcome set_image https://xxx.png")
            return
        wc["image_url"] = url
        wc["send_image"] = True
        self.config["welcome_config"] = wc
        self.config.save_config()
        yield event.plain_result(f"✅ 欢迎图片已设置为：{url}")

    @welcome.command("show")
    async def cmd_show(self, event: AstrMessageEvent):
        """查看当前入群欢迎配置"""
        wc = self.config.get("welcome_config", {})
        whitelist = self.config.get("whitelist", [])
        enabled = self.config.get("enable", True)

        lines = [
            f"🔧 状态：{'🟢 已启用' if enabled else '🔴 已禁用'}",
            f"🛡️ 白名单：{whitelist if whitelist else '（空=所有群生效）'}",
            f"🃏 群聊卡片：{'✅' if wc.get('send_card') else '❌'} 目标群={wc.get('card_group_id', '当前群')}",
            f"📨 合并转发：{'✅' if wc.get('send_forward') else '❌'} 共 {len(wc.get('forward_nodes', []))} 条消息节点",
            f"🖼️ 欢迎图片：{'✅' if wc.get('send_image') else '❌'} {wc.get('image_url', '未设置')[:60]}",
        ]
        yield event.plain_result("\n".join(lines))

    @welcome.command("clear")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_clear(self, event: AstrMessageEvent):
        """清除所有已保存的欢迎内容（保留白名单）"""
        wc = self.config.get("welcome_config", {})
        wc["forward_nodes"] = []
        wc["image_url"] = ""
        wc["card_group_id"] = ""
        wc["send_card"] = False
        wc["send_forward"] = False
        wc["send_image"] = False
        self.config["welcome_config"] = wc
        self.config.save_config()
        yield event.plain_result("✅ 已清除所有欢迎内容（白名单不变）。")

    # ══════════════════════════════════════════════════════════════════
    # 事件监听：新成员加群
    # ══════════════════════════════════════════════════════════════════

    @filter.event_message_type(filter.EventMessageType.ALL)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_notice_group_increase(self, event: AstrMessageEvent):
        """当收到群成员增加通知时触发欢迎流程"""
        if not self.config.get("enable", True):
            return

        raw = event.message_obj.raw_message
        notice_type = raw.get("notice_type", "")
        if notice_type != "group_increase":
            return

        group_id = str(raw.get("group_id", ""))
        user_id = str(raw.get("user_id", ""))
        if not group_id or not user_id:
            logger.warning("[GroupWelcome] 无法获取 group_id 或 user_id，跳过")
            return

        # 白名单检查
        whitelist = self.config.get("whitelist", [])
        whitelist_str = [str(g) for g in whitelist]
        if whitelist_str and group_id not in whitelist_str:
            logger.info(f"[GroupWelcome] 群 {group_id} 不在白名单中，跳过")
            return

        logger.info(f"[GroupWelcome] 检测到新成员 {user_id} 加入群 {group_id}")

        # 获取 bot 客户端
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )
        if not isinstance(event, AiocqhttpMessageEvent):
            logger.warning("[GroupWelcome] 非 aiocqhttp 事件，跳过")
            return
        bot = event.bot

        wc = self.config.get("welcome_config", {})

        # 发送群聊卡片
        if wc.get("send_card", True):
            await self._send_group_card(bot, user_id, group_id, wc)

        # 发送合并转发聊天记录
        if wc.get("send_forward", True):
            await self._send_stored_forward(bot, user_id, group_id, wc)

        # 发送图片
        if wc.get("send_image", True):
            await self._send_welcome_image(bot, user_id, group_id, wc)

        event.stop_event()

    # ══════════════════════════════════════════════════════════════════
    # 辅助方法
    # ══════════════════════════════════════════════════════════════════

    async def _extract_forward_nodes(self, event: AstrMessageEvent) -> list[Comp.Node]:
        """从事件消息中提取合并转发节点。支持多种路径：
        1. Reply 的 chain 中有 Node/Nodes → 直接提取
        2. Reply 的 chain 中有 Forward（ID 引用）→ get_forward_msg API
        3. Reply.chain 为空 → 用 Reply.id 调 get_msg → 找 Forward → get_forward_msg
        4. 当前消息中有 Node/Nodes → 直接提取
        5. 当前消息中有 Forward → get_forward_msg API
        """
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
            AiocqhttpMessageEvent,
        )

        bot = event.bot if isinstance(event, AiocqhttpMessageEvent) else None
        msgs = event.get_messages()

        # 打印调试信息，方便排查
        comp_types = [type(c).__name__ for c in msgs]
        logger.info(f"[GroupWelcome] 消息链组件类型: {comp_types}")

        # ── 路径 1 & 2：从引用（Reply）中提取 ─────────────────────
        for comp in msgs:
            if not isinstance(comp, Comp.Reply):
                continue

            logger.info(
                f"[GroupWelcome] 发现 Reply: id={comp.id}, "
                f"chain_len={len(comp.chain) if comp.chain else 0}"
            )

            # 1a. Reply.chain 中存在 → 直接找 Node/Nodes/Forward
            if comp.chain:
                nodes = self._find_nodes_in_chain(comp.chain)
                if nodes:
                    logger.info(f"[GroupWelcome] 从 Reply.chain 中提取到 {len(nodes)} 个 Node")
                    return nodes

                # 1b. Reply.chain 中可能有 Forward 引用
                if bot:
                    for c in comp.chain:
                        if isinstance(c, Comp.Forward) and c.id:
                            nodes = await self._fetch_forward_by_id(bot, str(c.id))
                            if nodes:
                                return nodes

            # 1c. Reply.chain 为空 → 用消息 ID 拉取原始消息
            if bot and comp.id:
                try:
                    ret = await bot.call_action("get_msg", message_id=int(comp.id))
                    logger.info(f"[GroupWelcome] get_msg 返回: {ret}")
                    if ret and "message" in ret:
                        raw_msg = ret["message"]
                        # 原始消息可能是 Forward 类型
                        if isinstance(raw_msg, list):
                            for seg in raw_msg:
                                seg_type = seg.get("type", "")
                                if seg_type == "forward":
                                    fid = seg.get("data", {}).get("id", "")
                                    if fid:
                                        nodes = await self._fetch_forward_by_id(bot, str(fid))
                                        if nodes:
                                            return nodes
                        # 也可能是 dict 格式
                        elif isinstance(raw_msg, dict):
                            seg_type = raw_msg.get("type", "")
                            if seg_type == "forward":
                                fid = raw_msg.get("data", {}).get("id", "")
                                if fid:
                                    nodes = await self._fetch_forward_by_id(bot, str(fid))
                                    if nodes:
                                        return nodes
                except Exception as e:
                    logger.error(f"[GroupWelcome] get_msg 失败: {e}")

        # ── 路径 3 & 4：从当前消息中提取 ─────────────────────────
        nodes = self._find_nodes_in_chain(msgs)
        if nodes:
            logger.info(f"[GroupWelcome] 从当前消息中提取到 {len(nodes)} 个 Node")
            return nodes

        if bot:
            for comp in msgs:
                if isinstance(comp, Comp.Forward) and comp.id:
                    nodes = await self._fetch_forward_by_id(bot, str(comp.id))
                    if nodes:
                        return nodes

        # ── 最终未找到，打印完整消息链便于调试 ─────────────────
        logger.warning("[GroupWelcome] 未能从任何路径提取到合并转发节点")
        for i, c in enumerate(msgs):
            logger.info(f"[GroupWelcome]   [{i}] {type(c).__name__}: {c}")
        return []

    async def _fetch_forward_by_id(self, bot, forward_id: str) -> list[Comp.Node]:
        """通过 get_forward_msg API 获取合并转发内容（含递归解析嵌套转发）"""
        try:
            logger.info(f"[GroupWelcome] 尝试 get_forward_msg, id={forward_id}")
            ret = await bot.call_action("get_forward_msg", message_id=forward_id)
            if ret and "messages" in ret:
                nodes = await self._parse_forward_api_response(
                    ret["messages"], bot=bot
                )
                logger.info(f"[GroupWelcome] get_forward_msg 返回 {len(nodes)} 个 Node")
                return nodes
        except Exception as e:
            logger.error(f"[GroupWelcome] get_forward_msg 失败: {e}")
        return []

    @staticmethod
    def _find_nodes_in_chain(chain: list) -> list[Comp.Node]:
        """在消息链中查找 Node/Nodes"""
        nodes = []
        for comp in chain:
            if isinstance(comp, Comp.Node):
                nodes.append(comp)
            elif isinstance(comp, Comp.Nodes):
                nodes.extend(comp.nodes)
        return nodes

    @staticmethod
    async def _parse_forward_api_response(
        messages: list,
        bot=None,
        depth: int = 0,
    ) -> list[Comp.Node]:
        """将 get_forward_msg API 返回的 messages 列表解析为 Node 列表。

        递归策略：
        - text/image/face/at → 直接保留
        - forward（嵌套转发）→ 立即调用 get_forward_msg 尝试解析内容
          成功 → 递归解析内部消息，展开的子消息平铺到当前层级
          失败（NapCat retcode=1200 内层消息）→ 静默跳过，不产生占位符
        - node（内联节点）→ 解析为 Comp.Node，内部嵌套继续递归
        """
        MAX_DEPTH = 5
        if depth > MAX_DEPTH:
            logger.warning("[GroupWelcome] _parse_forward_api_response 达到最大深度")
            return []

        nodes: list[Comp.Node] = []
        for msg in messages:
            sender = msg.get("sender", {})
            uin = str(sender.get("user_id", "0"))
            name = sender.get("nickname", "")
            raw_content = msg.get("message") or msg.get("content") or []
            content: list[Comp.BaseMessageComponent] = []

            for seg in raw_content:
                seg_type = seg.get("type", "")
                seg_data = seg.get("data", {})

                if seg_type == "text":
                    content.append(Comp.Plain(text=seg_data.get("text", "")))

                elif seg_type == "image":
                    url = seg_data.get("url", "")
                    file = seg_data.get("file", "")
                    if url and url.startswith("http"):
                        content.append(Comp.Image.fromURL(url))
                    elif file:
                        content.append(Comp.Image.fromFileSystem(file))

                elif seg_type == "face":
                    content.append(Comp.Face(id=seg_data.get("id", 0)))

                elif seg_type == "at":
                    content.append(Comp.At(qq=str(seg_data.get("qq", ""))))

                elif seg_type == "forward":
                    # ── 嵌套转发：完整保留原结构，不解构、不递归拆解 ──
                    content.append(_RawForward(seg_data))

                elif seg_type == "node":
                    # ── 内联 node：递归解析其 content ──
                    inner = Comp.Node(
                        uin=str(seg_data.get("user_id", "0")),
                        name=seg_data.get("nickname", ""),
                        content=[],
                    )
                    for ns in (seg_data.get("content") or []):
                        nt = ns.get("type", "")
                        nd = ns.get("data", {})
                        if nt == "text":
                            inner.content.append(Comp.Plain(text=nd.get("text", "")))
                        elif nt == "image":
                            inner.content.append(
                                Comp.Image.fromURL(nd["url"])
                                if nd.get("url", "").startswith("http")
                                else Comp.Image.fromFileSystem(nd.get("file", ""))
                            )
                        elif nt == "face":
                            inner.content.append(Comp.Face(id=nd.get("id", 0)))
                        elif nt == "at":
                            inner.content.append(Comp.At(qq=str(nd.get("qq", ""))))
                        elif nt == "forward":
                            # 完整保留嵌套 forward 段
                            inner.content.append(_RawForward(nd))
                    content.append(inner)

            # 当前消息有内容（非全为已展开的嵌套转发）则作为独立节点
            if content:
                nodes.append(Comp.Node(uin=uin, name=name, content=content))

        return nodes

    async def _send_group_card(self, bot, user_id: str, group_id: str, wc: dict):
        """通过临时会话发送群聊卡片"""
        try:
            card_group_id = wc.get("card_group_id", "") or group_id
            contact_msg = [{
                "type": "contact",
                "data": {"type": "group", "id": str(card_group_id)},
            }]
            await bot.call_action(
                "send_private_msg",
                user_id=user_id,
                group_id=group_id,
                message=contact_msg,
            )
            logger.info(f"[GroupWelcome] 群聊卡片已发送 -> {user_id}")
        except Exception as e:
            logger.error(f"[GroupWelcome] 发送群聊卡片失败: {e}")

    async def _send_stored_forward(self, bot, user_id: str, group_id: str, wc: dict):
        """发送已存储的合并转发聊天记录"""
        try:
            stored = wc.get("forward_nodes", [])
            if not stored:
                logger.info("[GroupWelcome] 未存储 forward_nodes，跳过合并转发")
                return

            nodes = [_deserialize_node(item) for item in stored]
            nodes_obj = Comp.Nodes(nodes=nodes)
            messages = (await nodes_obj.to_dict())["messages"]

            # 先尝试带 group_id（临时会话），失败则回退
            try:
                await bot.call_action(
                    "send_private_forward_msg",
                    user_id=user_id,
                    group_id=group_id,
                    messages=messages,
                )
            except Exception:
                await bot.call_action(
                    "send_private_forward_msg",
                    user_id=user_id,
                    messages=messages,
                )
            logger.info(f"[GroupWelcome] 合并转发已发送 -> {user_id}")
        except Exception as e:
            logger.error(f"[GroupWelcome] 发送合并转发失败: {e}")

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
                img = Comp.Image.fromURL(image_url)
            else:
                img = Comp.Image.fromFileSystem(image_url)
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
        logger.info("GroupWelcomePlugin 已卸载")


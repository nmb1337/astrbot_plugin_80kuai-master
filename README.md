# astrbot_plugin_group_welcome

> 🌟 QQ 群入群欢迎插件 —— 新成员加群时通过**临时会话**自动推送群聊卡片、合并转发聊天记录和图片。

## ✨ 功能

- 🔔 **监听加群事件**：捕获 OneBot v11 的 `group_increase` 通知
- 💬 **临时会话推送**：通过 QQ 临时会话（非好友私聊）向新成员发送欢迎内容
- 🃏 **群聊卡片**：发送推荐加群群名片
- 📨 **合并转发聊天记录**：⭐ **发送一条 QQ 合并转发消息给机器人即可捕获**，之后新成员加群自动转发
- 🖼️ **图片**：支持 HTTP URL 或本地路径的欢迎图片
- 🛡️ **群白名单**：仅对白名单内的群生效

---

## 🚀 快速上手

### 1. 安装

将插件放入 AstrBot 的 `data/plugins/`，在 WebUI 中启用。

### 2. 设置白名单

在 WebUI 插件配置中填写需要生效的群号列表，如 `["123456789"]`。

### 3. 捕获聊天记录（核心功能 ⭐）

```
① 在 QQ 群里发送一条「合并转发」消息（长按多选消息 → 合并转发）
② 长按/右键那条合并转发消息 → 引用（回复）
③ 输入 /welcome set_forward 并发送
④ 机器人回复 "✅ 已捕获 N 条转发消息节点"
```

之后每当有新成员加群，机器人就会**原样转发**这条聊天记录给新成员。

### 4. 设置群聊卡片

```
/welcome set_card 123456789    → 设置推荐加群的群号
/welcome set_card               → 使用当前群号
```

### 5. 设置欢迎图片

```
/welcome set_image https://example.com/welcome.png
```

或先发送一张图片，然后引用它发送 `/welcome set_image`（不填参数自动提取引用消息中的图片）。

### 6. 查看 / 清除配置

```
/welcome show     → 查看当前全部配置
/welcome clear    → 清除所有欢迎内容
```

---

## ⚙️ WebUI 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `enable` | bool | 总开关 |
| `whitelist` | list | 群号白名单，空 = 所有群生效 |
| `welcome_config.send_card` | bool | 是否发送群聊卡片 |
| `welcome_config.card_group_id` | string | 推荐群号，空 = 当前群 |
| `welcome_config.send_forward` | bool | 是否发送合并转发 |
| `welcome_config.forward_nodes` | list | 已捕获的转发节点（由指令自动填写） |
| `welcome_config.send_image` | bool | 是否发送图片 |
| `welcome_config.image_url` | string | 图片 URL 或本地路径 |

> 💡 `forward_nodes` 推荐通过 `/welcome set_forward` 指令自动捕获，无需手动编辑。

---

## 🔧 依赖

- **AstrBot** >= v3.4.28
- **aiocqhttp** 平台适配器（OneBot v11，如 NapCat / Lagrange）

> 合并转发消息仅 OneBot v11 平台支持。

## 📄 License

MIT


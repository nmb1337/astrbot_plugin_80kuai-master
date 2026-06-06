# astrbot_plugin_group_welcome

> 🌟 QQ 群入群欢迎插件 —— 新成员加群时通过临时会话自动推送群聊卡片、合并转发聊天记录和图片。

## ✨ 功能

- 🔔 **监听加群事件**：捕获 OneBot v11 的 `group_increase` 通知
- 💬 **临时会话推送**：通过 QQ 临时会话（非好友私聊）向新成员发送欢迎内容
- 🃏 **群聊卡片**：发送推荐加群 / 群名片卡片
- 📨 **合并转发聊天记录**：模拟多人聊天记录，以合并转发消息形式呈现
- 🖼️ **图片**：支持 HTTP URL 或本地路径的欢迎图片
- 🛡️ **群白名单**：仅对白名单内的群生效，避免干扰

## 📦 安装

将插件目录放入 AstrBot 的 `data/plugins/` 下：

```bash
cd AstrBot/data/plugins
git clone https://github.com/YourName/astrbot_plugin_group_welcome.git
```

然后在 WebUI 的「插件管理」中启用本插件。

## ⚙️ 配置

通过 AstrBot WebUI → 插件管理 → 找到「群聊入群欢迎」→ 点击配置：

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `enable` | bool | 是否启用插件 |
| `whitelist` | list | 群白名单，如 `["123456789"]`；为空则所有群生效 |
| `welcome_config.send_card` | bool | 是否发送群聊卡片 |
| `welcome_config.card_group_id` | string | 卡片推荐的目标群号，留空使用当前群 |
| `welcome_config.send_forward` | bool | 是否发送合并转发聊天记录 |
| `welcome_config.forward_nodes` | list | 合并转发的节点列表（见下方示例） |
| `welcome_config.send_image` | bool | 是否发送图片 |
| `welcome_config.image_url` | string | 图片 URL 或本地绝对路径 |

### forward_nodes 配置示例

```json
[
  {
    "uin": "10001",
    "name": "系统提示",
    "content": [
      {"type": "plain", "text": "👋 欢迎加入本群！请先阅读群公告。"}
    ]
  },
  {
    "uin": "10002",
    "name": "管理员",
    "content": [
      {"type": "plain", "text": "有问题可以随时 @管理员 哦～"},
      {"type": "image", "file": "https://example.com/guide.png"}
    ]
  }
]
```

每个节点字段：
- `uin`：显示的 QQ 号（字符串）
- `name`：显示的昵称
- `content`：消息内容数组，每项 `{"type": "plain"|"image", "text"|"file": "..."}`

## 🔧 依赖

- **AstrBot** >= v3.4.28
- **aiocqhttp** 平台适配器（OneBot v11，如 NapCat / Lagrange）

> 合并转发消息仅 OneBot v11 平台支持。

## 📄 License

MIT


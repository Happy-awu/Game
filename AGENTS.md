# battery_runner

多人 2D 瓦片游戏服务器。纯 Python 标准库 + pygame（仅客户端）。
无构建步骤，无测试，无 lint/typecheck 工具。

## 运行

```bash
python server.py          # 启动于 127.0.0.1:8888
python cilentTest.py      # 带 pygame 窗口的交互客户端
```

## 文件

- **`standard.py`** — Entity → Mob → Player 继承体系，以及 Tile/Chunk/Cross 辅助类。客户端依赖 `pygame`。
- **`server.py`** — 游戏服务端：`EtyManger`、`Map`、`Server`、`GameCommand`。单一文件 ~587 行。顶部有 CONFIG 字典。
- **`cilentTest.py`** — 带 pygame 渲染、物理和 pickle 协议网络的客户端。
- **`装备&武器的草稿.md`** — 游戏设计文档：职业、武器、物品、状态效果、地图、生物。

## 协议

TCP socket，消息为 `pickle` 序列化的字典：
`{"cmd_name": "...", "params": {...}}`
响应：`{"status": "ok"/"error", "data": ...}`

**安全**：pickle 反序列化不可信任的网络数据是危险的 —— 切勿在非信任网络上暴露此服务端。

## 约定

- 所有代码、注释、文档字符串均为中文。
- 线程安全：通过 `threading.Lock` 保护 `EtyManger`（players、mobs、entities 字典）。
- 空间划分：世界 → 瓦片（32px）→ 区块（16×16 瓦片）。
- 离线玩家数据追加写入 `offline_players.jsonl`（JSON Lines 格式）。

## 关键细节

- 心跳超时：**10 秒**（作为参数传给 `remove_timeout_players`），由守护线程每 **15 秒** 检查一次。客户端应约每 3 秒发送一次心跳。
- `Server.handle_client` 的 socket 超时：300 秒（来自 CONFIG）。
- 客户端测试每个玩家会打开 **两个** socket：一个用于游戏指令，一个用于心跳。
- 不存在 server0.py —— 旧文档中的遗留引用已过时。
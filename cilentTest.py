import socket
import time
import pickle
from standard import Player, Entity, Mob, Tile, Chunk, Cross
import threading
import pygame
from typing import Dict, List, Optional, Tuple


HOST = '127.0.0.1'
PORT = 8888


class Action:
    """游戏客户端渲染、动画、地图显示模块"""

    # 渲染类型分类（便于归类维护）
    class Type:
        TILE = "tile"
        PLAYER = "player"
        MOB = "mob"
        ENTITY = "entity"
        EFFECT = "effect"
        UI = "ui"

    class Node:
        """单个渲染节点"""
        def __init__(self, render_type: str, image: pygame.Surface,
                     world_pos: Tuple[float, float], layer: int = 0):
            self.type = render_type
            self.image = image
            self.world_pos = world_pos
            self.layer = layer
            self.visible = True

    CHUNK_TILES = 16  # 每个区块包含的瓦片数（与服务端一致）

    def __init__(self, width: int = 800, height: int = 600,
                 title: str = "Battery Runner", tile_size: int = 32):
        pygame.init()
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(title)
        self.clock = pygame.time.Clock()
        self.running = False
        self.tile_size = tile_size

        # 分类渲染节点池: {type: [Node, ...]}
        self.nodes: Dict[str, List["Action.Node"]] = {
            t: [] for t in [
                self.Type.TILE, self.Type.PLAYER, self.Type.MOB,
                self.Type.ENTITY, self.Type.EFFECT, self.Type.UI
            ]
        }

        # 图标缓存: {name: pygame.Surface}
        self.icons: Dict[str, pygame.Surface] = {}

        # 摄像机偏移（世界坐标 → 屏幕坐标转换）
        self.cam_x: float = 0.0
        self.cam_y: float = 0.0

        # 可视瓦片范围（用于区块裁剪）
        self.view_h: int = 15
        self.view_v: int = 15

        # 瓦片地图区块存储: {(chunk_x, chunk_y): Chunk}
        self.tile_chunks: Dict[Tuple[int, int], Chunk] = {}

        # 瓦片属性定义（与服务端保持一致）
        self.tile_properties: Dict[int, Dict] = {
            0: {"name": "grass", "walkable": True, "color": (34, 139, 34)},
            1: {"name": "wall", "walkable": False, "color": (139, 90, 43)},
            2: {"name": "water", "walkable": False, "color": (30, 144, 255)},
        }

        # 玩家/网络状态（由外部赋值，run 方法自动使用）
        self.player: Optional[Player] = None
        self.player_node: Optional["Action.Node"] = None
        self.server_socket: Optional[socket.socket] = None

        # 运行时状态
        self.last_nearby_sync: float = 0.0
        self.last_sync: float = 0.0
        self.server_x: float = 0.0
        self.server_y: float = 0.0
        self._prev_on_ground: bool = False
        self._jump_cooldown: int = 0
        self._jump_charge: int = 0

    # ==================== 图标管理 ====================

    def load_icon(self, name: str, path: str, size: Optional[Tuple[int, int]] = None) -> bool:
        """从文件加载图标到缓存，若成功返回 True"""
        try:
            img = pygame.image.load(path)
            if size:
                img = pygame.transform.scale(img, size)
            self.icons[name] = img
            return True
        except pygame.error as e:
            print(f"加载图标失败 {path}: {e}")
            return False

    def get_icon(self, name: str) -> Optional[pygame.Surface]:
        """获取缓存的图标"""
        return self.icons.get(name)

    def make_icon(self, name: str, color: Tuple[int, int, int],
                  size: Tuple[int, int] = (32, 32)) -> pygame.Surface:
        """直接创建纯色图标（无需文件）"""
        surf = pygame.Surface(size)
        surf.fill(color)
        self.icons[name] = surf
        return surf

    # ==================== 节点管理 ====================

    def add_node(self, node: "Action.Node"):
        """添加一个渲染节点到对应分类"""
        if node.type in self.nodes:
            self.nodes[node.type].append(node)

    def add_nodes(self, nodes: List["Action.Node"]):
        for n in nodes:
            self.add_node(n)

    def clear_type(self, render_type: str):
        """清空指定分类的所有节点"""
        if render_type in self.nodes:
            self.nodes[render_type].clear()

    def clear_all(self):
        """清空所有节点"""
        for t in self.nodes:
            self.nodes[t].clear()

    def get_nodes_by_type(self, render_type: str) -> List["Action.Node"]:
        """获取指定分类的所有节点"""
        return self.nodes.get(render_type, [])

    # ==================== 坐标转换 ====================

    def world_to_screen(self, world_x: float, world_y: float) -> Tuple[float, float]:
        """世界坐标 → 屏幕坐标"""
        return world_x - self.cam_x, world_y - self.cam_y

    def screen_to_world(self, screen_x: float, screen_y: float) -> Tuple[float, float]:
        """屏幕坐标 → 世界坐标"""
        return screen_x + self.cam_x, screen_y + self.cam_y

    def follow(self, world_x: float, world_y: float,
               screen_width: int, screen_height: int):
        """摄像机跟随目标（居中）"""
        self.cam_x = world_x - screen_width // 2
        self.cam_y = world_y - screen_height // 2

    # ==================== 瓦片坐标转换 ====================

    def world_to_tile(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """世界坐标 → 瓦片坐标"""
        return int(world_x // self.tile_size), int(world_y // self.tile_size)

    def tile_to_chunk(self, tile_x: int, tile_y: int) -> Tuple[int, int]:
        """瓦片坐标 → 区块坐标"""
        return tile_x // self.CHUNK_TILES, tile_y // self.CHUNK_TILES

    def world_to_chunk(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """世界坐标 → 区块坐标"""
        return self.tile_to_chunk(*self.world_to_tile(world_x, world_y))

    # ==================== 区块地图管理 ====================

    def load_chunk(self, chunk: Chunk) -> None:
        """存储一个区块的瓦片数据"""
        self.tile_chunks[(chunk.chunk_x, chunk.chunk_y)] = chunk

    def get_chunk(self, chunk_x: int, chunk_y: int) -> Optional[Chunk]:
        """获取指定区块的瓦片数据"""
        return self.tile_chunks.get((chunk_x, chunk_y))

    def remove_chunk(self, chunk_x: int, chunk_y: int) -> None:
        """卸载指定区块"""
        self.tile_chunks.pop((chunk_x, chunk_y), None)

    def clear_chunks(self):
        """卸载所有区块"""
        self.tile_chunks.clear()

    def get_tile(self, tile_x: int, tile_y: int) -> Optional[Tile]:
        """从已加载的区块中获取单个瓦片 ID"""
        cx, cy = self.tile_to_chunk(tile_x, tile_y)
        chunk = self.tile_chunks.get((cx, cy))
        if chunk is None:
            return None
        local_x = tile_x - cx * self.CHUNK_TILES
        local_y = tile_y - cy * self.CHUNK_TILES
        if 0 <= local_y < len(chunk.tiles) and 0 <= local_x < len(chunk.tiles[0]):
            return chunk.tiles[local_y][local_x]
        return None

    # ==================== 视距计算 ====================

    def get_visible_tile_range(self, world_x: float, world_y: float,
                               h_view: int, v_view: int) -> Dict[str, int]:
        """
        根据玩家坐标和视距，计算可见瓦片的坐标范围
        :param world_x, world_y: 玩家世界坐标
        :param h_view: 横向可视瓦片数
        :param v_view: 纵向可视瓦片数
        :return: {"min_x": int, "max_x": int, "min_y": int, "max_y": int}
        """
        tx, ty = self.world_to_tile(world_x, world_y)
        return {
            "min_x": tx - h_view, "max_x": tx + h_view,
            "min_y": ty - v_view, "max_y": ty + v_view,
        }

    def get_visible_chunks(self, world_x: float, world_y: float,
                           h_view: int, v_view: int) -> List[Tuple[int, int]]:
        """
        计算可见区域涉及哪些区块
        :return: [(chunk_x, chunk_y), ...]
        """
        r = self.get_visible_tile_range(world_x, world_y, h_view, v_view)
        min_cx, min_cy = self.tile_to_chunk(r["min_x"], r["min_y"])
        max_cx, max_cy = self.tile_to_chunk(r["max_x"], r["max_y"])
        chunks = []
        for cy in range(min_cy, max_cy + 1):
            for cx in range(min_cx, max_cx + 1):
                chunks.append((cx, cy))
        return chunks

    def get_visible_tiles(self, world_x: float, world_y: float,
                          h_view: int, v_view: int) -> List[Tuple[int, int, Tile]]:
        """
        从已加载的区块数据中，获取视距内所有瓦片
        :return: [(tile_x, tile_y, Tile), ...]（仅返回已加载区块中的瓦片）
        """
        r = self.get_visible_tile_range(world_x, world_y, h_view, v_view)
        result = []
        for ty in range(r["min_y"], r["max_y"] + 1):
            for tx in range(r["min_x"], r["max_x"] + 1):
                tid = self.get_tile(tx, ty)
                if tid is not None:
                    result.append((tx, ty, tid))
        return result

    # ==================== 区块拼接渲染 ====================

    def render_tile_chunks(self):
        """
        刷新视口内所有可见瓦片节点（自动拼接区块）
        """
        self.clear_type(self.Type.TILE)
        for (cx, cy), chunk in list(self.tile_chunks.items()):
            chunk_wx = cx * self.CHUNK_TILES * self.tile_size
            chunk_wy = cy * self.CHUNK_TILES * self.tile_size
            chunk_sx, chunk_sy = self.world_to_screen(chunk_wx, chunk_wy)
            chunk_px = self.CHUNK_TILES * self.tile_size
            if (chunk_sx + chunk_px < 0 or chunk_sx > self.screen.get_width()
                    or chunk_sy + chunk_px < 0 or chunk_sy > self.screen.get_height()):
                continue
            for local_y, row in enumerate(chunk.tiles):
                for local_x, tile_obj in enumerate(row):
                    tile_wx = chunk_wx + local_x * self.tile_size
                    tile_wy = chunk_wy + local_y * self.tile_size
                    image = tile_obj.image
                    if image is None:
                        color = self.tile_properties.get(tile_obj.tile_id, {}).get("color", (0, 0, 0))
                        key = f"_fallback_{tile_obj.tile_id}"
                        if key not in self.icons:
                            surf = pygame.Surface((self.tile_size, self.tile_size))
                            surf.fill(color)
                            self.icons[key] = surf
                        image = self.icons[key]
                    node = self.Node(self.Type.TILE, image, (tile_wx, tile_wy))
                    self.add_node(node)

    # ==================== 渲染 ====================

    def render(self):
        """绘制所有节点到屏幕（按类型顺序分层渲染）"""
        if self.tile_chunks:
            cam_tx = int(self.cam_x // self.tile_size)
            cam_ty = int(self.cam_y // self.tile_size)
            self.render_tile_chunks()
        layer_order = [
            self.Type.TILE,
            self.Type.EFFECT,
            self.Type.ENTITY,
            self.Type.MOB,
            self.Type.PLAYER,
            self.Type.UI,
        ]
        for t in layer_order:
            for node in self.nodes[t]:
                if not node.visible:
                    continue
                sx, sy = self.world_to_screen(*node.world_pos)
                self.screen.blit(node.image, (sx, sy))

        # 区块边框（棕色 5px）
        chunk_px = self.CHUNK_TILES * self.tile_size
        for (cx, cy) in self.tile_chunks:
            wx = cx * chunk_px
            wy = cy * chunk_px
            sx, sy = self.world_to_screen(wx, wy)
            if (sx + chunk_px < 0 or sx > self.screen.get_width()
                    or sy + chunk_px < 0 or sy > self.screen.get_height()):
                continue
            pygame.draw.rect(self.screen, (139, 90, 43), (sx, sy, chunk_px, chunk_px), 5)

    def render_tilemap(self, tiles: List[Tuple[int, int, int]],
                       tile_colors: Dict[int, Tuple[int, int, int]]):
        """
        快速渲染瓦片地图
        :param tiles: [(tile_x, tile_y, tile_id), ...]
        :param tile_colors: {tile_id: (R, G, B)}
        """
        for tx, ty, tid in tiles:
            color = tile_colors.get(tid, (0, 0, 0))
            wx = tx * self.tile_size
            wy = ty * self.tile_size
            sx, sy = self.world_to_screen(wx, wy)
            pygame.draw.rect(self.screen, color,
                             (sx, sy, self.tile_size, self.tile_size))

    def render_text(self, text: str, pos: Tuple[float, float],
                    color: Tuple[int, int, int] = (255, 255, 255),
                    size: int = 16):
        """在屏幕坐标上渲染文字"""
        font = pygame.font.Font(None, size)
        surf = font.render(text, True, color)
        self.screen.blit(surf, pos)

    # ==================== 碰撞检测 ====================

    def _on_ground(self) -> bool:
        cx = self.player.x + self.tile_size // 2 #type: ignore
        cy = self.player.y + self.tile_size + 1 #type: ignore
        tx, ty = int(cx // self.tile_size), int(cy // self.tile_size)
        tile = self.get_tile(tx, ty)
        if tile is None:
            return False
        prop = self.tile_properties.get(tile.tile_id)
        return prop is not None and not prop.get("walkable", False)

    def can_walk(self, world_x: float, world_y: float) -> bool:
        for ox, oy in [(0, 0), (self.tile_size - 1, 0),
                       (0, self.tile_size - 1), (self.tile_size - 1, self.tile_size - 1)]:
            tx, ty = int((world_x + ox) // self.tile_size), int((world_y + oy) // self.tile_size)
            tile = self.get_tile(tx, ty)
            if tile is None:
                return False
            prop = self.tile_properties.get(tile.tile_id)
            if not (prop and prop.get("walkable", False)):
                return False
        return True

    # ==================== 网络接收 ====================

    def drain_recv(self) -> list:
        sock = self.server_socket
        if sock is None:
            return []
        sock.settimeout(0)
        results = []
        from io import BytesIO
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                buf = BytesIO(data)
                while True:
                    try:
                        results.append(pickle.load(buf))
                    except:
                        break
            except:
                break
        sock.settimeout(None)
        return results

    # ==================== 游戏循环 ====================

    def run(self, tick_rate: int = 60):
        self.running = True
        self.last_nearby_sync = 0.0
        self.last_sync = 0.0
        if self.player:
            self.server_x = self.player.x
            self.server_y = self.player.y
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    break

            if self.player is not None and self.server_socket is not None and self.player_node is not None:
                now = time.time()
                vec=self.player.vec

                #物理更新
                on_ground = self._on_ground()

                # 跳跃冷却：落地后 6 帧内不能起跳
                if on_ground:
                    if not self._prev_on_ground:
                        self._jump_cooldown = 6
                    elif self._jump_cooldown > 0:
                        self._jump_cooldown -= 1
                self._prev_on_ground = on_ground

                # 跳跃蓄力：跳跃后不断施加力并逐渐衰减为0
                if self._jump_charge:
                    self._jump_charge -= 2
                    vec.add_force(Cross(0, -2.53*self._jump_charge))

                # 地面接触 → 清零垂直速度（在力结算之前）
                if on_ground and vec.velocity.y is not None and vec.velocity.y > 0:
                    vec.velocity.y = 0.0

                # 键盘输入 → 施加力
                keys = pygame.key.get_pressed()
                if keys[pygame.K_LEFT] or keys[pygame.K_a]:  vec.add_force(Cross(-2.75, 0))
                if keys[pygame.K_RIGHT] or keys[pygame.K_d]: vec.add_force(Cross(2.75, 0))
                if keys[pygame.K_SPACE] and on_ground:
                    if self._jump_cooldown == 0: 
                        self._jump_charge = 8
                        vec.add_force(Cross(0, -20.24))

                #常规量计算

                # 摩擦力
                if vec.velocity.x is not None:
                    if abs(vec.velocity.x) < vec.phy_consts.friction:
                        vec.velocity.x = 0.0
                    elif vec.velocity.x > 0:
                        vec.velocity.x -= vec.phy_consts.friction
                    else:
                        vec.velocity.x += vec.phy_consts.friction

                # 物理结算：力 → 加速度 → 速度
                vec.update_acc()
                vec.update_vel()

                # 重力（脚下无承托则下落）
                if not on_ground:
                    mass = vec.phy_consts.mass
                    g = vec.phy_consts.gravity
                    vec.add_force(Cross(0, mass * g))

                # 速度 → 位移（分轴碰撞检测）
                vx = vec.velocity.x if vec.velocity.x is not None else 0.0
                vy = vec.velocity.y if vec.velocity.y is not None else 0.0
                if vx:
                    new_x = self.player.x + vx
                    if self.can_walk(new_x, self.player.y):
                        self.player.x = new_x
                    else:
                        vec.velocity.x = 0.0
                if vy:
                    new_y = self.player.y + vy
                    if self.can_walk(self.player.x, new_y):
                        self.player.y = new_y
                    else:
                        if vy > 0:  # 下落 → 逐像素贴近地面
                            for dy in range(1, int(vy) + 1):
                                test_y = self.player.y + dy
                                if not self.can_walk(self.player.x, test_y):
                                    break
                                self.player.y = test_y
                        vec.velocity.y = 0.0
                if vx or vy:
                    self.player_node.world_pos = (self.player.x, self.player.y)  #type: ignore

                # 同步服务端
                if now - self.last_sync >= 0.0167:
                    self.last_sync = now
                    self.server_socket.send(pickle.dumps({
                        "cmd_name": "MovePlayer",
                        "params": {"player": self.player, "new_x": self.player.x, "new_y": self.player.y}
                    }))

                # 查询周边 + 渲染
                if now - self.last_nearby_sync >= 0.0167:
                    self.last_nearby_sync = now
                    self.server_socket.send(pickle.dumps({
                        "cmd_name": "GetNearby",
                        "params": {"player": self.player, "range_tiles": 15}
                    }))

                for resp in self.drain_recv():
                    data = resp.get("data", {})
                    # 移动同步：仅在服务端报错时回滚到上次确认位置
                    if resp.get("status") == "error":
                        self.player.x, self.player.y = self.server_x, self.server_y
                        self.player_node.world_pos = (self.player.x, self.player.y)
                    elif "new_x" in data and "new_y" in data:
                        self.server_x, self.server_y = data["new_x"], data["new_y"]

                    if "players" in data or "mobs" in data or "entities" in data:
                        self.clear_type(self.Type.MOB)
                        self.clear_type(self.Type.ENTITY)
                        self.nodes[self.Type.PLAYER] = [n for n in self.nodes[self.Type.PLAYER]
                                                        if n is self.player_node]
                        for obj in data.get("players", []):
                            if obj.pid == self.player.pid:
                                continue
                            self.add_node(self.Node(self.Type.PLAYER, self.get_icon("other_player"), (obj.x, obj.y))) #type: ignore
                        for obj in data.get("mobs", []):
                            self.add_node(self.Node(self.Type.MOB, self.get_icon("mob"), (obj.x, obj.y))) #type: ignore
                        for obj in data.get("entities", []):
                            self.add_node(self.Node(self.Type.ENTITY, self.get_icon("entity"), (obj.x, obj.y))) #type: ignore

                self.follow(self.player.x, self.player.y, self.screen.get_width(), self.screen.get_height())
                self.render_text(
                    f"POS ({self.player.x:.0f}, {self.player.y:.0f})  TILE ({int(self.player.x//self.tile_size)}, {int(self.player.y//self.tile_size)})",
                    (10, 10), (255, 255, 255), 18
                )

            self.screen.fill((0, 0, 0))
            self.render()
            pygame.display.flip()
            self.clock.tick(tick_rate)
        pygame.quit()

def test_client():
    action = Action(800, 600, "Battery Runner — Client Test")
    sep = "-" * 40

    # ========== 准备渲染资源 ==========
    action.make_icon("player", (0, 255, 0), (32, 32))
    action.make_icon("grass", (34, 139, 34), (32, 32))
    action.make_icon("wall", (139, 90, 43), (32, 32))
    action.make_icon("entity", (160, 160, 160), (32, 32))  # 灰色-Entity
    action.make_icon("mob", (139, 69, 19), (32, 32))       # 棕色-Mob
    action.make_icon("other_player", (0, 150, 255), (32, 32))  # 蓝色-其他玩家

    # ========== 连接服务端 ==========
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.settimeout(5)
        srv.connect((HOST, PORT))
        print(f"[DONE] 服务端连接成功  {HOST}:{PORT}")
    except Exception as e:
        print(f"[ERR] 服务端连接失败: {e}")
        return
    srv_hb = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_hb.connect((HOST, PORT))

    # ========== 添加玩家 ==========
    pid = f"player_{int(time.time())}"
    player = Player(can_block=True, health=100, damage=10, backpack_slots=20, pid=pid)
    player.x = 160.0
    GROUND_TILE_Y = 16
    player.y = float(GROUND_TILE_Y * 32 - 32)
    srv.send(pickle.dumps({"cmd_name": "AddPlayer", "params": {"player": player}}))
    resp = pickle.loads(srv.recv(4096))
    print(f"[DONE] AddPlayer: {resp}")

    # ========== 加载测试地图（3×3 区块，边界围墙） ==========
    MAP_TILES_W = 3 * Action.CHUNK_TILES   # 48
    MAP_TILES_H = 3 * Action.CHUNK_TILES
    for cy in range(3):
        for cx in range(3):
            tiles = []
            for ly in range(Action.CHUNK_TILES):
                row = []
                for lx in range(Action.CHUNK_TILES):
                    gx = cx * Action.CHUNK_TILES + lx
                    gy = cy * Action.CHUNK_TILES + ly
                    if gx == 0 or gx == MAP_TILES_W - 1 or gy == 0 or gy == MAP_TILES_H - 1:
                        row.append(Tile(tile_id=1, image=action.get_icon("wall")))
                    elif gy < GROUND_TILE_Y:
                        row.append(Tile(tile_id=0, image=action.get_icon("grass")))
                    else:
                        row.append(Tile(tile_id=1, image=action.get_icon("wall")))
                tiles.append(row)
            action.load_chunk(Chunk(tiles, (cx, cy), cx, cy))
    print("[DONE] 测试地图加载完毕 (48×48 瓦片，边界围墙)")

    # ========== 玩家渲染节点 ==========
    player_node = Action.Node(Action.Type.PLAYER, action.get_icon("player"), (player.x, player.y)) #type: ignore
    action.add_node(player_node)

    # ========== 心跳线程 ==========
    window_ready = threading.Event()
    def net_loop():
        window_ready.wait()
        while action.running:
            try:
                srv_hb.send(pickle.dumps({"cmd_name": "Heartbeat", "params": {"player": player}}))
                pickle.loads(srv_hb.recv(4096))
            except:
                break
            time.sleep(3)
        srv_hb.close()
    threading.Thread(target=net_loop, daemon=True).start()

    # ========== 装配 Action 实例并运行 ==========
    action.player = player
    action.player_node = player_node
    action.server_socket = srv
    print("[WND] 方向键 / WASD 移动玩家，关闭窗口退出")
    print(sep)
    window_ready.set()
    action.run()

    # ========== 清理 ==========
    srv.send(pickle.dumps({"cmd_name":"OfflinePlayer", "params":{"player": player}}))
    time.sleep(0.05)
    srv.close()
    srv_hb.close()
    pygame.quit()
    print("[DONE] 测试结束")

if __name__ == "__main__":
    test_client()
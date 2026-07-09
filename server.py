import socket
import threading
import logging
from typing import Dict, List, Tuple, Optional, Any
import json
import time
import pickle
from standard import Entity, Mob, Player

# ==================== 配置参数 ====================
CONFIG = {
    "host": "127.0.0.1",
    "port": 8888,
    "timeout": 300,
    "tile_size": 32,
    "chunk_tiles": 16,
    "map_width_tiles": 100,      # 地图宽度（瓦片数）
    "map_height_tiles": 100,     # 地图高度（瓦片数）
    "default_tile_id": 0,        # 默认草地
    "player_view_tiles": 15,     # 玩家可视瓦片范围
    "attack_range": 2,           # 攻击范围（瓦片）
    "offline_player_file": "offline_players.jsonl",
}

def setup_logger():
    """全局日志配置（只调用一次）"""
    logging.root.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.root.addHandler(console_handler)
    logging.root.setLevel(logging.INFO)

# ==================== 地图管理类 ====================
class Map:
    TILE_SIZE = CONFIG["tile_size"]
    CHUNK_TILES = CONFIG["chunk_tiles"]
    CHUNK_SIZE = TILE_SIZE * CHUNK_TILES

    # 定义瓦片类型（示例，可扩展）
    TILE_PROPERTIES = {
        0: {"name": "grass", "walkable": True},
        1: {"name": "wall", "walkable": False},
        2: {"name": "water", "walkable": False},
    }

    def __init__(self, width_tiles: int, height_tiles: int, default_tile_id: int = 0):
        self.map_width = width_tiles
        self.map_height = height_tiles
        self.default_tile = default_tile_id
        self.map_data: List[List[int]] = self._init_empty_map()
        self.lock = threading.Lock()

    def _init_empty_map(self, random_walls: bool = False) -> List[List[int]]:
        """
        初始化地图数据
        :param random_walls: 是否随机生成少量墙体（True）还是全草地（False）
        """
        import random
        data = []
        for y in range(self.map_height):
            row = []
            for x in range(self.map_width):
                # 边界强制设为墙体（瓦片ID 1）
                if x == 0 or y == 0 or x == self.map_width - 1 or y == self.map_height - 1:
                    tile = 1
                else:
                    if random_walls:
                        # 5% 的概率生成墙体，其余为草地（0）
                        tile = 0 if random.random() > 0.05 else 1
                    else:
                        tile = 0  # 全草地
                row.append(tile)
            data.append(row)   # 每生成一行后加入 data
        return data

    def is_walkable(self, world_x: float, world_y: float) -> bool:
        """检查某个世界坐标是否可行走（不越界且瓦片可行走）"""
        tile_x, tile_y = self.world_to_tile(world_x, world_y)
        if not (0 <= tile_x < self.map_width and 0 <= tile_y < self.map_height):
            return False
        tile_id = self.map_data[tile_y][tile_x]
        return self.TILE_PROPERTIES.get(tile_id, {}).get("walkable", False)

    @staticmethod
    def world_to_tile(world_x: float, world_y: float) -> Tuple[int, int]:
        return int(world_x // Map.TILE_SIZE), int(world_y // Map.TILE_SIZE)

    @staticmethod
    def tile_to_chunk(tile_x: int, tile_y: int) -> Tuple[int, int]:
        return tile_x // Map.CHUNK_TILES, tile_y // Map.CHUNK_TILES

    def get_visible_tiles(self, world_x: float, world_y: float, h_view: int, v_view: int) -> List[Tuple[int, int, int]]:
        tile_x, tile_y = self.world_to_tile(world_x, world_y)
        min_x = max(0, tile_x - h_view)
        max_x = min(self.map_width - 1, tile_x + h_view)
        min_y = max(0, tile_y - v_view)
        max_y = min(self.map_height - 1, tile_y + v_view)
        visible = []
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                visible.append((x, y, self.map_data[y][x]))
        return visible

# ==================== 实体管理类（改进） ====================
class EtyManger:
    """实体管理器：管理所有玩家和怪物的对象实例，支持区块化存储和线程安全"""
    TILE_SIZE = CONFIG["tile_size"]
    CHUNK_TILES = CONFIG["chunk_tiles"]

    def __init__(self, offline_file: str = CONFIG["offline_player_file"]):
        self.lock = threading.Lock()
        # 玩家存储：pid -> Player 对象实例
        self.players: Dict[str, Player] = {}
        # 怪物存储：区块坐标 (chunk_x, chunk_y) -> {mid: Mob 对象}
        self.mobs: Dict[Tuple[int, int], Dict[str, Mob]] = {}
        self.offline_file = offline_file
        self.next_mob_id = 1000   # 简单自增ID生成器
        # 通用实体存储：区块坐标 (chunk_x, chunk_y) -> {eid: Entity 对象}
        self.entities: Dict[Tuple[int, int], Dict[str, Entity]] = {}
        self.next_entity_id = 2000  # 通用实体ID生成器

    # ========== 坐标转换工具（静态方法） ==========
    @staticmethod
    def world_to_tile(world_x: float, world_y: float) -> Tuple[int, int]:
        """世界坐标 → 瓦片坐标"""
        return int(world_x // EtyManger.TILE_SIZE), int(world_y // EtyManger.TILE_SIZE)

    @staticmethod
    def tile_to_chunk(tile_x: int, tile_y: int) -> Tuple[int, int]:
        """瓦片坐标 → 区块坐标"""
        return tile_x // EtyManger.CHUNK_TILES, tile_y // EtyManger.CHUNK_TILES

    @staticmethod
    def world_to_chunk(world_x: float, world_y: float) -> Tuple[int, int]:
        """世界坐标直接 → 区块坐标"""
        tx, ty = EtyManger.world_to_tile(world_x, world_y)
        return EtyManger.tile_to_chunk(tx, ty)

    # ========== 玩家管理 ==========
    def add_player(self, player: Player) -> None:
        """
        添加一个已有 Player 对象到世界
        """
        pid = player.pid
        with self.lock:
            if pid in self.players:
                raise ValueError(f"玩家 {pid} 已存在")
            player.last_heartbeat = time.time()
            self.players[pid] = player
            logging.info(f"玩家 {pid} 加入，位置 ({player.x:.1f}, {player.y:.1f})")

    def get_player(self, pid: str) -> Optional[Player]:
        with self.lock:
            return self.players.get(pid)

    def get_all_players(self) -> Dict[str, Player]:
        with self.lock:
            return self.players.copy()

    def update_player_position(self, player: Player, new_x: float, new_y: float) -> None:
        with self.lock:
            stored = self.players.get(player.pid)
            if stored:
                stored.x = new_x
                stored.y = new_y

    def remove_player(self, player: Player) -> None:
        pid = player.pid
        with self.lock:
            if pid not in self.players:
                return
            del self.players[pid]
            # 离线数据持久化（写入文件）
            offline_record = {
                "player_id": pid,
                "disconnect_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "world_pos": (player.x, player.y),
                "tile_pos": self.world_to_tile(player.x, player.y),
                "hp": player.health,
                "damage": player.damage,
            }
        # 在锁外写文件，避免长时间阻塞
        try:
            with open(self.offline_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(offline_record, ensure_ascii=False) + "\n")
        except Exception as e:
            logging.error(f"写入离线玩家 {pid} 失败: {e}")

    def update_heartbeat(self, player: Player) -> None:
        with self.lock:
            stored = self.players.get(player.pid)
            if stored:
                stored.last_heartbeat = time.time()

    # ========== 怪物管理 ==========
    def _generate_mob_id(self) -> str:
        """生成唯一怪物ID"""
        self.next_mob_id += 1
        return f"mob_{self.next_mob_id}"

    def add_mob(self, mob: Mob) -> str:
        """
        添加一个已有 Mob 对象到世界，自动分配区块
        :return: 怪物ID
        """
        if not mob.mid:
            mob.mid = self._generate_mob_id()
        mob_id = mob.mid
        chunk = self.world_to_chunk(mob.x, mob.y)
        with self.lock:
            if chunk not in self.mobs:
                self.mobs[chunk] = {}
            self.mobs[chunk][mob_id] = mob
        logging.debug(f"添加怪物 {mob_id} 于区块 {chunk}，位置 ({mob.x:.1f}, {mob.y:.1f})")
        return mob_id

    def remove_mob(self, mob: Mob) -> None:
        """删除怪物（死亡/刷新）"""
        chunk = self.world_to_chunk(mob.x, mob.y)
        with self.lock:
            if chunk in self.mobs and mob.mid in self.mobs[chunk]:
                del self.mobs[chunk][mob.mid]
                if not self.mobs[chunk]:
                    del self.mobs[chunk]

    def get_mob(self, mob_id: str, world_x: float, world_y: float) -> Optional[Mob]:
        """根据ID和大致位置获取怪物对象（位置用于定位区块）"""
        chunk = self.world_to_chunk(world_x, world_y)
        with self.lock:
            return self.mobs.get(chunk, {}).get(mob_id)

    def get_mobs_in_range(self, world_x: float, world_y: float, range_tiles: int = 15) -> List[Mob]:
        """
        获取指定世界坐标周围一定范围内的所有怪物对象
        :param range_tiles: 瓦片范围
        """
        center_chunk = self.world_to_chunk(world_x, world_y)
        offset = range_tiles // self.CHUNK_TILES + 1
        result = []
        with self.lock:
            for dx in range(-offset, offset+1):
                for dy in range(-offset, offset+1):
                    chunk = (center_chunk[0]+dx, center_chunk[1]+dy)
                    if chunk in self.mobs:
                        result.extend(self.mobs[chunk].values())
        return result

    def move_mob(self, mob: Mob, new_wx: float, new_wy: float) -> bool:
        """
        移动怪物（自动处理跨区块）
        :return: 是否成功
        """
        with self.lock:
            old_chunk = self.world_to_chunk(mob.x, mob.y)
            if old_chunk not in self.mobs or mob.mid not in self.mobs[old_chunk]:
                return False
            del self.mobs[old_chunk][mob.mid]
            if not self.mobs[old_chunk]:
                del self.mobs[old_chunk]
            mob.x = new_wx
            mob.y = new_wy
            new_chunk = self.world_to_chunk(new_wx, new_wy)
            if new_chunk not in self.mobs:
                self.mobs[new_chunk] = {}
            self.mobs[new_chunk][mob.mid] = mob
            return True

    # ========== 通用实体管理 ==========
    def _generate_entity_id(self) -> str:
        """生成唯一通用实体ID"""
        self.next_entity_id += 1
        return f"entity_{self.next_entity_id}"

    def add_entity(self, entity: Entity, eid: Optional[str] = None) -> str:
        """
        添加一个已有 Entity 对象到世界，自动分配区块
        :return: 实体ID
        """
        entity_id = eid if eid is not None else self._generate_entity_id()
        entity.eid = entity_id
        chunk = self.world_to_chunk(entity.x, entity.y)
        with self.lock:
            if chunk not in self.entities:
                self.entities[chunk] = {}
            self.entities[chunk][entity_id] = entity
        logging.debug(f"添加通用实体 {entity_id} 于区块 {chunk}，位置 ({entity.x:.1f}, {entity.y:.1f})")
        return entity_id

    def get_entity(self, eid: str, world_x: float, world_y: float) -> Optional[Entity]:
        """根据ID和大致位置获取通用实体（位置用于定位区块）"""
        chunk = self.world_to_chunk(world_x, world_y)
        with self.lock:
            return self.entities.get(chunk, {}).get(eid)

    def remove_entity(self, entity: Entity) -> None:
        """删除通用实体"""
        eid = entity.eid
        chunk = self.world_to_chunk(entity.x, entity.y)
        with self.lock:
            if chunk in self.entities and eid in self.entities[chunk]:
                del self.entities[chunk][eid]
                if not self.entities[chunk]:
                    del self.entities[chunk]

    def move_entity(self, entity: Entity, new_wx: float, new_wy: float) -> bool:
        """
        移动通用实体（自动处理跨区块）
        :return: 是否成功
        """
        with self.lock:
            old_chunk = self.world_to_chunk(entity.x, entity.y)
            if old_chunk not in self.entities or entity.eid not in self.entities[old_chunk]:
                return False
            del self.entities[old_chunk][entity.eid]
            if not self.entities[old_chunk]:
                del self.entities[old_chunk]
            entity.x = new_wx
            entity.y = new_wy
            new_chunk = self.world_to_chunk(new_wx, new_wy)
            if new_chunk not in self.entities:
                self.entities[new_chunk] = {}
            self.entities[new_chunk][entity.eid] = entity
            return True

    def get_entities_in_range(self, world_x: float, world_y: float,
                              range_tiles: int = 15) -> List[Entity]:
        """获取指定世界坐标周围一定范围内的所有通用实体"""
        center_chunk = self.world_to_chunk(world_x, world_y)
        offset = range_tiles // self.CHUNK_TILES + 1
        result = []
        with self.lock:
            for dx in range(-offset, offset + 1):
                for dy in range(-offset, offset + 1):
                    chunk = (center_chunk[0] + dx, center_chunk[1] + dy)
                    if chunk in self.entities:
                        result.extend(self.entities[chunk].values())
        return result

    # ========== 通用查询 ==========
    def get_nearby_entities(self, world_x: float, world_y: float, range_tiles: int) -> Dict[str, List]:
        """
        获取附近所有实体（玩家 + 怪物 + 通用实体）
        返回格式: {"players": [Player对象], "mobs": [Mob对象], "entities": [Entity对象]}
        """
        players_near = []
        with self.lock:
            for pid, player in self.players.items():
                if abs(player.x - world_x) <= range_tiles * self.TILE_SIZE and \
                   abs(player.y - world_y) <= range_tiles * self.TILE_SIZE:
                    players_near.append(player)
        mobs_near = self.get_mobs_in_range(world_x, world_y, range_tiles)
        entities_near = self.get_entities_in_range(world_x, world_y, range_tiles)
        return {"players": players_near, "mobs": mobs_near, "entities": entities_near}

    # ========== 全局清理 ==========
    def clear_all(self) -> None:
        with self.lock:
            self.players.clear()
            self.mobs.clear()
            self.entities.clear()

    # ========== 心跳超时检查（可选） ==========
    def remove_timeout_players(self, timeout_seconds: int = 90) -> List[str]:
        """移除心跳超时的玩家，返回被移除的玩家ID列表"""
        now = time.time()
        to_remove = []
        with self.lock:
            for pid, player in self.players.items():
                if now - getattr(player, "last_heartbeat", now) > timeout_seconds:
                    to_remove.append(player)
        for p in to_remove:
            self.remove_player(p)
        return [p.pid for p in to_remove]

# ==================== 指令系统（改进） ====================
class GameCommand:
    def __init__(self, EtyManger: EtyManger, game_map: Map, server: 'Server'):
        self.EtyManger = EtyManger
        self.game_map = game_map
        self.server = server
        self.commands = {}
        self._register_commands()

    def _register_commands(self):
        # 格式：指令名 -> (处理函数, 参数名列表)
        self.commands["AddPlayer"] = (self.add_player, ["player"])
        self.commands["MovePlayer"] = (self.move_player, ["player", "new_x", "new_y"])
        self.commands["AttackMob"] = (self.attack_mob, ["player", "mob"])
        self.commands["GetNearby"] = (self.get_nearby, ["player", "range_tiles"])
        self.commands["GetVisibleMap"] = (self.get_visible_map, ["player", "h_view", "v_view"])
        self.commands["Heartbeat"] = (self.heartbeat, ["player"])
        self.commands["AddEntity"] = (self.add_entity, ["entity"])
        self.commands["MoveEntity"] = (self.move_entity, ["entity", "new_x", "new_y"])
        self.commands["RemoveEntity"] = (self.remove_entity, ["entity"])
        self.commands["OfflinePlayer"] = (self.offline_player, ["player"])

    def execute(self, conn: socket.socket, addr: Tuple[str, int], cmd_dict: Dict) -> Any:
        cmd_name = cmd_dict.get("cmd_name")
        params = cmd_dict.get("params", {})
        if cmd_name not in self.commands:
            error = {"status": "error", "msg": f"未知指令 {cmd_name}"}
            self.server.send_message(conn, addr, pickle.dumps(error))
            return False
        func, arg_names = self.commands[cmd_name]
        # 构建参数（从 params 中提取所需的参数）
        args = [params.get(name) for name in arg_names]
        try:
            result = func(*args)
            # 统一返回格式
            response = {"status": "ok", "data": result} if result is not None else {"status": "ok"}
            self.server.send_message(conn, addr, pickle.dumps(response))
            return True
        except Exception as e:
            error_resp = {"status": "error", "msg": str(e)}
            self.server.send_message(conn, addr, pickle.dumps(error_resp))
            return False

    # ---------- 具体指令实现 ----------
    def add_player(self, player: Player):
        if self.EtyManger.get_player(player.pid) is not None:
            raise Exception("玩家已存在")
        if not self.game_map.is_walkable(player.x, player.y):
            raise Exception("出生点不可行走")
        self.EtyManger.add_player(player)
        return {"pid": player.pid, "pos": (player.x, player.y)}

    def move_player(self, player: Player, new_x: float, new_y: float):
        if not player or not player.is_alive:
            raise Exception("玩家无效或已死亡")
        if not self.game_map.is_walkable(new_x, new_y):
            raise Exception("不可行走")
        self.EtyManger.update_player_position(player, new_x, new_y)
        logging.info(f"玩家 {player.pid} 移动到 ({new_x:.0f}, {new_y:.0f})")
        self.server.broadcast_nearby(player.pid, {"type": "move", "pid": player.pid, "x": new_x, "y": new_y})
        return {"new_x": new_x, "new_y": new_y}

    def attack_mob(self, player: Player, mob: Mob):
        if not player or not player.is_alive:
            raise Exception("玩家无效")
        dist = ((player.x - mob.x)**2 + (player.y - mob.y)**2)**0.5 / self.game_map.TILE_SIZE
        if dist > CONFIG["attack_range"]:
            raise Exception("距离过远")
        damage_dealt = player.attack(mob)
        if not mob.is_alive:
            self.EtyManger.remove_mob(mob)
            result = {"killed": mob.mid}
        else:
            result = {"mob_id": mob.mid, "remaining_hp": mob.health, "damage": damage_dealt}
        self.server.broadcast_nearby(player.pid, {"type": "attack", "pid": player.pid, "target": mob.mid, "result": result})
        return result

    def get_nearby(self, player: Player, range_tiles: int = 15):
        if not player:
            raise Exception("玩家不存在")
        nearby = self.EtyManger.get_nearby_entities(player.x, player.y, range_tiles)
        mob_count = len(nearby.get("mobs", []))
        ent_count = len(nearby.get("entities", []))
        logging.info(f"玩家 {player.pid} 查询附近实体: {mob_count} 怪物, {ent_count} 通用实体")
        return nearby

    def get_visible_map(self, player: Player, h_view: int = 0, v_view: int = 0):
        if not player:
            raise Exception("玩家不存在")
        if h_view is None:
            h_view = CONFIG["player_view_tiles"]
        if v_view is None:
            v_view = CONFIG["player_view_tiles"]
        tiles = self.game_map.get_visible_tiles(player.x, player.y, h_view, v_view)
        return {"center": (player.x, player.y), "tiles": tiles}

    def heartbeat(self, player: Player):
        self.EtyManger.update_heartbeat(player)
        return {"time": time.time()}

    def list_players(self):
        players = self.EtyManger.get_all_players()
        return {pid: {"hp": p.health, "pos": (p.x, p.y)} for pid, p in players.items()}

    # ---------- 通用实体指令 ----------
    def add_entity(self, entity: Entity):
        result_id = self.EtyManger.add_entity(entity, entity.eid or None)
        return {"eid": result_id, "pos": (entity.x, entity.y)}

    def move_entity(self, entity: Entity, new_x: float, new_y: float):
        if not self.EtyManger.move_entity(entity, new_x, new_y):
            raise Exception("实体移动失败")
        return {"eid": entity.eid, "new_pos": (new_x, new_y)}

    def remove_entity(self, entity: Entity):
        self.EtyManger.remove_entity(entity)
        return {"eid": entity.eid}

    def offline_player(self, player: Player):
        self.EtyManger.remove_player(player)
        return {"pid": player.pid}

# ==================== 网络服务器类====================
class Server:
    def __init__(self):
        self.EtyManger = EtyManger(CONFIG["offline_player_file"])
        self.game_map = Map(CONFIG["map_width_tiles"], CONFIG["map_height_tiles"], CONFIG["default_tile_id"])
        self.command_handler = GameCommand(self.EtyManger, self.game_map, self)
        self.clients: Dict[str, socket.socket] = {}  # pid -> conn，用于主动推送
        self.clients_lock = threading.Lock()

    def send_message(self, conn: socket.socket, addr: Tuple[str, int], data: bytes) -> bool:
        try:
            conn.send(data)
            return True
        except (ConnectionResetError, BrokenPipeError, OSError):
            logging.error(f"发送给 {addr} 失败，连接已断开")
            return False

    def broadcast_nearby(self, exclude_pid: str, message: Dict):
        """向除了 exclude_pid 之外的附近玩家广播消息（简单实现：广播给所有在线玩家）"""
        # 实际可根据位置过滤，这里简化
        with self.clients_lock:
            for pid, conn in self.clients.items():
                if pid == exclude_pid:
                    continue
                try:
                    conn.send(pickle.dumps(message))
                except:
                    pass

    def handle_client(self, conn: socket.socket, addr: Tuple[str, int]):
        logging.info(f"新客户端连接 {addr}")
        conn.settimeout(CONFIG["timeout"])
        try:
            while True:
                raw_data = conn.recv(65535)
                if not raw_data:
                    logging.info(f"{addr} 连接正常关闭")
                    break
                # 反序列化指令
                try:
                    cmd_dict = pickle.loads(raw_data)
                except pickle.UnpicklingError:
                    logging.warning(f"{addr} 发送了无效的pickle数据")
                    self.send_message(conn, addr, pickle.dumps({"status": "error", "msg": "Invalid data format"}))
                    continue
                # 执行指令
                self.command_handler.execute(conn, addr, cmd_dict)
        except socket.timeout:
            logging.warning(f"{addr} 心跳超时，断开连接")
        except ConnectionResetError:
            logging.error(f"{addr} 连接意外重置")
        except Exception as e:
            logging.error(f"{addr} 处理异常: {e}")
        finally:
            # 移除客户端，如果是玩家则记录离线
            # 注意：这里无法从消息中直接获得pid，可维护addr->pid映射，简化起见不处理
            conn.close()
            logging.info(f"{addr} 连接已关闭")

    def start(self):
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((CONFIG["host"], CONFIG["port"]))
        server_sock.listen(5)
        logging.info(f"服务器启动，监听 {CONFIG['host']}:{CONFIG['port']}")

        # 启动心跳检查线程（可选）
        def heartbeat_checker():
            while True:
                time.sleep(15)
                removed = self.EtyManger.remove_timeout_players(10)
                for pid in removed:
                    logging.info(f"玩家 {pid} 心跳超时，自动移除")
        threading.Thread(target=heartbeat_checker, daemon=True).start()

        while True:
            conn, addr = server_sock.accept()
            client_thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
            client_thread.start()

# ==================== 主程序入口 ====================
if __name__ == "__main__":
    setup_logger()
    # 先创建Server实例（需要先占位，因为GameCommand需要引用server）
    server = Server()  # 临时
    # 启动服务器
    server.start()
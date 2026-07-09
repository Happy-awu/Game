# standard.py
from typing import List, Dict, Any, Optional, Tuple
import pygame

class Cross:
    '''
    一般的在平面直角坐标系坐标轴上的量
    值为负表示在负半轴上，反之为正半轴，值为 None 时无效
    '''
    def __init__(self, num_on_x: Optional[float], num_on_y: Optional[float]):
        self.x=num_on_x
        self.y=num_on_y

    def __repr__(self):
        return f"Cross(x={self.x}, y={self.y})"

    def __add__(self, other: "Cross") -> "Cross":
        def _add(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None:
                return b
            if b is None:
                return a
            return a + b
        return Cross(_add(self.x, other.x), _add(self.y, other.y))

    def __iadd__(self, other: "Cross") -> "Cross":
        def _iadd(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None:
                return b
            if b is None:
                return a
            return a + b
        self.x = _iadd(self.x, other.x)
        self.y = _iadd(self.y, other.y)
        return self

    def __sub__(self, other: "Cross") -> "Cross":
        def _sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None:
                return -b if b is not None else None
            if b is None:
                return a
            return a - b
        return Cross(_sub(self.x, other.x), _sub(self.y, other.y))

    def __isub__(self, other: "Cross") -> "Cross":
        def _isub(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None:
                return -b if b is not None else None
            if b is None:
                return a
            return a - b
        self.x = _isub(self.x, other.x)
        self.y = _isub(self.y, other.y)
        return self

class Entity:
    """所有游戏实体的基类，包含最基本的物理与空间属性"""
    class Vector:
        '''物理与矢量类，规范操作物理变化'''

        class PhysicalConsts:
            '''物理常量的定义'''
            def __init__(self):
                self.mass=1.0
                self.gravity=9.8
                self.damping=0.9
                self.friction=0.75

        def __init__(self):
            self.velocity=Cross(None, None)
            self.force=[]
            self.acceleration=[]

            self.phy_consts=self.PhysicalConsts()
        
        def update_acc(self):
            '''每 tick 清理 acceleration 列表'''
            mass = self.phy_consts.mass
            for f in self.force:
                ax = None
                ay = None
                if f.x is not None:
                    ax = f.x / mass if mass else 0.0
                if f.y is not None:
                    ay = f.y / mass if mass else 0.0
                self.acceleration.append(Cross(ax, ay))
            self.force.clear()

        def update_vel(self):
            '''每 tick 将加速度累加到速度，再施加阻尼与摩擦力'''
            if self.acceleration:
                total = Cross(None, None)
                for a in self.acceleration:
                    total += a
                self.velocity += total
                self.acceleration.clear()

            d = self.phy_consts.damping
            if self.velocity.x is not None:
                self.velocity.x *= d
            if self.velocity.y is not None:
                self.velocity.y *= d

            fr = self.phy_consts.friction
            if self.velocity.x is not None:
                if abs(self.velocity.x) < fr:
                    self.velocity.x = 0.0
                elif self.velocity.x > 0:
                    self.velocity.x -= fr
                else:
                    self.velocity.x += fr
            if self.velocity.y is not None:
                if abs(self.velocity.y) < fr:
                    self.velocity.y = 0.0
                elif self.velocity.y > 0:
                    self.velocity.y -= fr
                else:
                    self.velocity.y += fr

        def add_force(self, f: Cross):
            self.force.append(f)
    
    def __init__(self, visible: bool = True, has_collision: bool = True, affected_by_gravity: bool = True, eid: str = ""):
        """
        初始化实体基本属性
        :param visible: 是否可见（用于渲染）
        :param has_collision: 是否有碰撞体积（用于物理碰撞检测）
        :param affected_by_gravity: 是否受重力影响（用于运动模拟）
        """
        self.visible = visible
        self.has_collision = has_collision
        self.affected_by_gravity = affected_by_gravity
        self.eid = eid
        self.x=0.0
        self.y=0.0

        self.vec=self.Vector()

        if not self.affected_by_gravity:
            self.vec.phy_consts.gravity=0.0
    
    def set_visibility(self, visible: bool) -> None:
        """修改实体的可见性"""
        self.visible = visible
    
    def set_collision(self, enabled: bool) -> None:
        """启用/禁用碰撞体积"""
        self.has_collision = enabled
    
    def set_gravity_affected(self, affected: bool) -> None:
        """设置是否受重力影响"""
        self.affected_by_gravity = affected
    
    def __repr__(self) -> str:
        return f"Entity(visible={self.visible}, collision={self.has_collision}, gravity={self.affected_by_gravity})"


class Mob(Entity):
    """可战斗实体，继承自Entity，添加战斗相关属性"""
    
    def __init__(self, 
                 can_block: bool = True,
                 health: int = 100,
                 damage: int = 10,
                 mid: str = "",
                 **entity_kwargs):
        """
        初始化怪物/战斗实体
        :param can_block: 是否可以格挡（部分怪物可格挡攻击）
        :param health: 当前血量
        :param damage: 攻击力
        :param entity_kwargs: 传递给Entity基类的参数（visible, has_collision, affected_by_gravity）
        """
        super().__init__(**entity_kwargs)
        self.mid = mid
        self.can_block = can_block
        self._max_health = health   # 存储最大血量（可根据需求单独维护）
        self._health = health
        self.damage = damage
        self.is_alive = True
    
    @property
    def health(self) -> int:
        return self._health
    
    @health.setter
    def health(self, value: int) -> None:
        """设置血量，并自动处理死亡标志"""
        self._health = max(0, min(value, self._max_health))
        if self._health <= 0:
            self.is_alive = False
    
    @property
    def max_health(self) -> int:
        return self._max_health
    
    def take_damage(self, amount: int) -> int:
        """
        受到伤害，返回实际造成的伤害值（考虑格挡减伤）
        :param amount: 原始伤害值
        :return: 实际扣除的血量
        """
        if not self.is_alive:
            return 0
        final_damage = amount
        if self.can_block:
            # 简单格挡：减少50%伤害，可自行扩展
            final_damage = max(1, amount // 2)
        self.health -= final_damage
        return final_damage
    
    def attack(self, target: 'Mob') -> int:
        """
        攻击另一个Mob实体，返回造成的伤害
        :param target: 目标实体（必须为Mob或其子类）
        """
        if not self.is_alive:
            return 0
        return target.take_damage(self.damage)
    
    def heal(self, amount: int) -> int:
        """回复血量，返回实际回复量"""
        old_hp = self._health
        self.health += amount
        return self._health - old_hp
    
    def __repr__(self) -> str:
        return (f"Mob(health={self.health}/{self.max_health}, damage={self.damage}, "
                f"can_block={self.can_block}, alive={self.is_alive})")


class Player(Mob):
    """玩家实体，继承自Mob，添加背包等玩家专属功能"""
    
    def __init__(self,
                 backpack_slots: int = 20,
                 backpack_content: Optional[List[Dict[str, Any]]] = None,
                 pid : str = "",
                 last_heartbeat : float = 0.0,
                 **mob_kwargs):
        """
        初始化玩家
        :param backpack_slots: 背包格数
        :param backpack_content: 初始背包内容（列表，每个元素为物品字典）
        :param mob_kwargs: 传递给Mob类的参数（如health, damage, can_block等）
        """
        super().__init__(**mob_kwargs)
        self.backpack_slots = backpack_slots
        self.pid = pid
        self.last_heartbeat = last_heartbeat
        # 背包内容：列表，每个元素为 {"item_id": str, "name": str, "count": int, ...}
        self.backpack: List[Dict[str, Any]] = backpack_content if backpack_content is not None else []
        
        # 玩家特有属性（可扩展）
        self.level: int = 1
        self.exp: int = 0
    
    def add_item(self, item: Dict[str, Any]) -> bool:
        """
        向背包添加物品，返回是否成功
        :param item: 物品字典，至少包含 "item_id" 和 "count"
        """
        if len(self.backpack) >= self.backpack_slots:
            return False
        self.backpack.append(item)
        return True
    
    def remove_item(self, item_id: str, count: int = 1) -> bool:
        """
        根据物品ID移除指定数量的物品，返回是否成功
        简化实现：只移除背包中第一个匹配的物品（不考虑多个相同物品堆叠）
        """
        for i, item in enumerate(self.backpack):
            if item.get("item_id") == item_id:
                if item.get("count", 1) >= count:
                    item["count"] -= count
                    if item["count"] <= 0:
                        self.backpack.pop(i)
                    return True
        return False
    
    def get_backpack_items(self) -> List[Dict[str, Any]]:
        """返回背包物品列表的副本"""
        return self.backpack.copy()
    
    def gain_exp(self, amount: int) -> None:
        """增加经验值，并自动升级（示例：每100经验升一级）"""
        self.exp += amount
        required_exp = self.level * 100
        if self.exp >= required_exp:
            self.level += 1
            self.exp -= required_exp
            # 升级时增加最大血量和回复满血（可自定义）
            self._max_health += 20
            self._health = self._max_health
            print(f"玩家升级至 {self.level} 级！")
    
    def __repr__(self) -> str:
        return (f"Player(level={self.level}, exp={self.exp}, health={self.health}/{self.max_health}, "
                f"damage={self.damage}, backpack={len(self.backpack)}/{self.backpack_slots} items)")


class Tile:
    """地图瓦片，定义单个瓦片的渲染属性"""

    def __init__(self, tile_id: int = 0, image: Optional[pygame.Surface] = None, layer: int = 0, visible: bool = True):
        """
        初始化瓦片
        :param tile_id: 瓦片类型 ID（与服务端 tile_id 对应）
        :param image: 贴图（Surface）
        :param layer: 渲染层级（数值越大越靠前）
        :param visible: 是否可见
        """
        self.tile_id = tile_id
        self.image = image
        self.layer = layer
        self.visible = visible

    def __repr__(self) -> str:
        return f"Tile(id={self.tile_id}, image={self.image!r}, layer={self.layer})"


class Chunk:
    """地图区块，包含一组瓦片及其区块坐标"""

    def __init__(self, tiles: List[List[Tile]], chunk_id: Tuple[int, int], chunk_x: int, chunk_y: int):
        """
        初始化区块
        :param tiles: 二维瓦片 ID 列表 (tiles[y][x])
        :param chunk_id: 区块坐标 (chunk_x, chunk_y)
        """
        self.tiles = tiles
        self.chunk_id = chunk_id
        self.chunk_x = chunk_x
        self.chunk_y = chunk_y

    def __repr__(self) -> str:
        h = len(self.tiles) if self.tiles else 0
        w = len(self.tiles[0]) if self.tiles and self.tiles[0] else 0
        return f"Chunk(id={self.chunk_id}, tiles={w}x{h})"
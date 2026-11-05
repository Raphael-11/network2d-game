"""Fighter roster: stats and abilities. Shared by the server (rules) and the
client (character select screen). Visual styling lives in client/art.py.

Stat multipliers are relative to the baseline tuning in physics.py:
  speed  -> run speed / air control      weight -> knockback resistance
  power  -> damage dealt                 jump   -> jump height
  reach  -> attack hitbox length
"""

PROJ_KINDS = ["fireball", "bullet"]

ORDER = ["ragnar", "kira", "blaze", "titan", "vex", "luna", "rex", "aria"]
DEFAULT = "aria"


def _c(name, title, weapon, speed, weight, power, jump, reach, light, heavy, special, bio):
    return {"name": name, "title": title, "weapon": weapon, "speed": speed,
            "weight": weight, "power": power, "jump": jump, "reach": reach,
            "light": light, "heavy": heavy, "special": special, "bio": bio}


CHARACTERS = {
    "ragnar": _c("Ragnar", "The Storm Viking", "axe", 0.90, 1.25, 1.20, 0.92, 1.05,
                 "Axe Chop", "Skull Splitter",
                 {"kind": "slam", "cd": 80, "name": "Thunder Slam",
                  "desc": "Leap and crash down, sending a shockwave along the ground."},
                 "A berserker who answers every problem with a bigger axe."),
    "kira": _c("Kira", "Shadow of the Moon", "katana", 1.25, 0.82, 0.85, 1.08, 1.00,
               "Quick Slash", "Crescent Cut",
               {"kind": "dash", "cd": 55, "name": "Shadow Step",
                "desc": "Blink forward, untouchable, cutting through anyone in the way."},
               "Fast, fragile and gone before you see the blade."),
    "blaze": _c("Blaze", "Ember Sorcerer", "gauntlets", 1.00, 0.90, 1.00, 1.00, 0.85,
                "Flame Jab", "Inferno Palm",
                {"kind": "projectile", "proj": "fireball", "cd": 45, "speed": 520,
                 "dmg": 12, "kb": 1.1, "life": 50, "r": 16, "name": "Fireball",
                 "desc": "Hurl a slow, heavy fireball that blasts foes away."},
                "Keeps enemies at a distance with a wall of fire."),
    "titan": _c("Titan", "The Iron Colossus", "hammer", 0.78, 1.45, 1.30, 0.85, 1.15,
                "Hammer Jab", "Earthbreaker",
                {"kind": "armor", "cd": 210, "dur": 75, "name": "Iron Skin",
                 "desc": "Become unflinching for 2.5s: no stun, 70% less knockback."},
                "Slow as a glacier, and just as hard to move."),
    "vex": _c("Vex", "The Dust Gunslinger", "pistols", 1.10, 0.95, 0.90, 1.00, 0.90,
              "Pistol Whip", "Point Blank",
              {"kind": "projectile", "proj": "bullet", "cd": 24, "speed": 1150,
               "dmg": 6, "kb": 0.75, "life": 28, "r": 7, "name": "Quickdraw",
               "desc": "Fire a fast bullet. Low damage, very short cooldown."},
              "Never misses a shot, never pays a tab."),
    "luna": _c("Luna", "Witch of the Tides", "scythe", 0.95, 0.90, 1.00, 1.05, 1.25,
               "Reap", "Harvest Moon",
               {"kind": "pull", "cd": 100, "radius": 240, "name": "Lunar Tide",
                "desc": "Drag every nearby enemy toward you, stunning them."},
               "Her scythe reaches further than anyone expects."),
    "rex": _c("Rex", "The Wild Fang", "claws", 1.15, 1.10, 1.05, 1.10, 0.85,
              "Claw Swipe", "Rending Maul",
              {"kind": "pounce", "cd": 60, "name": "Savage Pounce",
               "desc": "Leap forward in an arc, mauling anything you land on."},
              "Raised by wolves. Still hunts like one."),
    "aria": _c("Aria", "Valkyrie of the Dawn", "spear", 1.00, 1.00, 1.00, 1.00, 1.10,
               "Spear Thrust", "Valhalla Lunge",
               {"kind": "rise", "cd": 75, "name": "Sky Lance",
                "desc": "Rocket upward, launching anyone above. Great recovery."},
               "Balanced in every way. The standard others are measured by."),
}


def get(char_id):
    return CHARACTERS.get(char_id, CHARACTERS[DEFAULT])

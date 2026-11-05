# Brawl Arena (Computer Networks Project #2)

Server: Python 3.9+ standard library only. Client: Python 3.13 (Windows) or
any Python with a pygame wheel, plus `pip install -r requirements.txt`.

## Play online (server on a Linux VPS, players on any PCs)

On the VPS (Debian/Ubuntu, as root):

    git clone https://github.com/Raphael-11/network2d-game.git /tmp/brawl
    bash /tmp/brawl/deploy/install_server.sh        # installs, tests, starts the systemd service

Open TCP port 5000 in the VPS provider's firewall / security group too.

On each player PC:

    git clone https://github.com/Raphael-11/network2d-game.git    (or "Download ZIP")
    Windows:      play.bat <VPS_IP>
    Linux/macOS:  ./play.sh <VPS_IP>

One player creates an arena, the others join it from the lobby, everyone picks
a fighter, and the host picks the arena and starts the battle.

## Code layout

```text
brawl_arena/
 common/
  protocol.py       message types, JSON codec, constants
  physics.py        deterministic stage, player, hit and KO logic
 server/
  server_core.py    accounts, lobby, rooms, game loop (transport-agnostic)
  transport_tcp.py  selectors-based TCP server
  transport_udp.py  UDP socket + reliability layer
  run_server.py     --transport tcp|udp --port N
 client/
  client_core.py    state, interpolation, input sampling
  ui.py             pygame lobby and game screens
  net_tcp.py
  net_udp.py
  run_client.py     --transport tcp|udp --host IP --port N
 tools/
  lossy_proxy.py    UDP/TCP proxy injecting loss, delay, jitter
  metrics.py        CSV logging and summary
 tests/
 test_core.py
```

Both server versions use the same transport interface:

```python
class ServerTransport:
    def send_reliable(player_id, msg): ...
    def send_unreliable(player_id, msg): ...
    def poll() -> list[tuple[int, dict]]: ...
    def on_disconnect(callback): ...
    def close_player(player_id): ...
```

## Game controls

The client opens in fullscreen mode.

The top-left HUD shows local FPS, heartbeat packet loss (`PL`), and TCP
round-trip ping.

| Action | Key |
|---|---|
| Move | `W` `A` `S` `D` / `Z` `Q` `S` `D` (AZERTY) / arrow keys |
| Jump / double jump | `W` or `Z`, Up arrow or Space |
| Fast-fall (tap) / drop through soft platform (hold) | `S` / Down arrow |
| Light attack | Left mouse button / `E` |
| Heavy attack (wind-up, big knockback) | `X` |
| Signature ability | `F` |
| Dodge (brief invulnerability) | `Q` / `A` / Shift |
| Forfeit match | Esc twice |

## Moveset (every fighter)

Hold a direction while attacking to pick the variant (`physics.MOVES`):

| | Neutral | Side | Down | In the air |
|---|---|---|---|---|
| Light | Jab | Lunge (dashing poke) | Sweep (low, pops up) | Down: Spike (knocks *down*) |
| Heavy | Launcher (uppercut) | Smash (stepping, strongest) | Quake (hits both sides) | Any: Cyclone (spin) |

## Arenas

The host picks the arena in the room screen (`common/maps.py`):

| Arena | Backdrop | Layout |
|---|---|---|
| Sky Ruins | `client/assets/Floating Castle Valley Panorama-3.png` | wide stone-arch island, twin slabs, high perch, outer ledges |
| Moonlit Harbor | `client/assets/Moonlit Pagoda Harbor Valley-2.png` | two docks with a deadly gap under a red bridge, pagoda roofs |
| Pagoda Citadel | `client/assets/Moonlit Pagoda Citadel and Floating Ruins-1.png` | violet citadel island with stepped platforms |

## Rendering

- `client/rig.py`: skeletal cut-out fighters. Each body part is painted once
  at high resolution (ink outline, cel shading, costume detail) and rotated
  onto a skeleton every frame; poses are blended for smooth animation.
- `client/portraits.py`: detailed comic portraits and in-battle heads.
- `client/stage.py`: follow camera (pan only, pixel-snapped), parallax painted
  backdrops with ambient life, per-arena stage art.
- Snapshots are interpolated on the server-tick timeline, so network jitter
  does not show up as stutter.

## Fighters

Eight original fighters (`common/characters.py`), each with its own stats
(power, speed, weight, jump, reach) and signature ability:

| Fighter | Weapon | Signature |
|---|---|---|
| Ragnar, the Storm Viking | axe | Thunder Slam: crash down, ground shockwave |
| Kira, Shadow of the Moon | katana | Shadow Step: invulnerable dash-through slash |
| Blaze, Ember Sorcerer | gauntlets | Fireball projectile |
| Titan, the Iron Colossus | hammer | Iron Skin: no stun, 70% less knockback |
| Vex, the Dust Gunslinger | pistols | Quickdraw: fast low-damage bullet |
| Luna, Witch of the Tides | scythe | Lunar Tide: pulls nearby enemies in |
| Rex, the Wild Fang | claws | Savage Pounce: leaping maul |
| Aria, Valkyrie of the Dawn | spear | Sky Lance: rising strike / recovery |

All rules run on the server (`common/physics.py`); the client only renders.
Portraits, fighters, stage art and sounds are generated in code; the only
asset files are the three painted backdrops in `client/assets/`.

## Status
- [x] common/protocol.py  - message types, validation, TCP framing
- [x] common/physics.py   - deterministic game rules (shared by TCP and UDP versions)
- [x] test_core.py        - headless tests (32 passing)
- [x] common/characters.py - 8-fighter roster, character select, signature abilities
- [x] server/server_core.py, transport_tcp.py, run_server.py - TCP lobby/room/game loop
- [x] client (pygame) + net_tcp.py, client_core.py, ui.py, run_client.py
- [ ] transport_udp.py (reliability layer, heartbeats)
- [ ] tools/lossy_proxy.py, metrics.py

## Run the tests
    python test_core.py

## Run the TCP version
    python -m server.run_server --transport tcp --port 5000
    python -m client.run_client --transport tcp --host 127.0.0.1 --port 5000 --name alice

Omit `--name` to type it in the login screen. Open two or three client windows
to play against yourself locally, or point `--host` at the server machine's
LAN IP to play across computers.

"""Arena layouts, shared by the server (collision) and the client (art).

Platforms are (x_left, x_right, y_surface, solid). Solid platforms cannot be
dropped through. "classic" is the original small test arena; ORDER lists the
arenas offered in the room screen.
"""

MAPS = {
    "classic": {
        "name": "Proving Grounds", "theme": "day", "bg": None,
        "platforms": [(340, 940, 480, True), (400, 560, 360, False), (720, 880, 360, False),
                      (570, 710, 250, False), (150, 280, 420, False), (1000, 1130, 420, False)],
        "spawns": [(500, 300), (640, 300), (780, 300)],
        "blast": (-200, 1480, -300, 940),
    },
    "sky_ruins": {
        "name": "Sky Ruins", "subtitle": "Emerald Citadel", "theme": "day",
        "bg": "Floating Castle Valley Panorama-3.png",
        "platforms": [(250, 1030, 520, True), (330, 520, 390, False), (760, 950, 390, False),
                      (545, 735, 265, False), (40, 200, 445, False), (1080, 1240, 445, False)],
        "spawns": [(420, 330), (640, 200), (860, 330)],
        "blast": (-380, 1660, -380, 1020),
    },
    "moon_harbor": {
        "name": "Moonlit Harbor", "subtitle": "Mind the gap", "theme": "harbor",
        "bg": "Moonlit Pagoda Harbor Valley-2.png",
        "platforms": [(170, 560, 500, True), (720, 1110, 500, True), (500, 780, 415, False),
                      (240, 420, 365, False), (860, 1040, 365, False), (565, 715, 255, False)],
        "spawns": [(330, 300), (640, 190), (950, 300)],
        "blast": (-360, 1640, -380, 1020),
    },
    "citadel": {
        "name": "Pagoda Citadel", "subtitle": "Under the dragon moon", "theme": "citadel",
        "bg": "Moonlit Pagoda Citadel and Floating Ruins-1.png",
        "platforms": [(300, 980, 500, True), (160, 320, 410, False), (960, 1120, 410, False),
                      (410, 580, 325, False), (700, 870, 325, False), (560, 720, 205, False)],
        "spawns": [(495, 260), (640, 150), (785, 260)],
        "blast": (-360, 1640, -400, 1020),
    },
}

ORDER = ["sky_ruins", "moon_harbor", "citadel"]
DEFAULT = "sky_ruins"


def get(map_id):
    return MAPS.get(map_id, MAPS["classic"])

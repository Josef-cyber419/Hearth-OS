from hearth import artfind
from hearth.library import Game

PNG = b"\x89PNG\r\n\x1a\nfake"

LISTING = """<html><body>
<a href="Super%20Mario%2064%20%28Europe%29%20%28En%2CFr%2CDe%29.png">x</a>
<a href="Super%20Mario%2064%20%28Japan%29.png">x</a>
<a href="Super%20Mario%2064%20%28USA%29.png">x</a>
<a href="Legend%20of%20Zelda%2C%20The%20-%20Ocarina%20of%20Time%20%28USA%29.png">x</a>
<a href="Mario%20Kart%2064%20%28USA%29%20%28Beta%29.png">x</a>
<a href="Mario%20Kart%2064%20%28USA%29.png">x</a>
<a href="?C=N;O=D">sort</a>
</body></html>"""


class Net:
    def __init__(self, listing=LISTING, down=False):
        self.listing, self.down, self.asked = listing, down, []

    def __call__(self, url):
        self.asked.append(url)
        if self.down:
            raise OSError("offline")
        if url.endswith("/"):
            return self.listing.encode() if "Named_Titles" in url else b"<html></html>"
        return PNG


def names():
    return artfind.index("n64", "Named_Titles", Net())


def test_exact_no_intro_name_wins():
    assert artfind.best_match("Super Mario 64 (Europe) (En,Fr,De)", names()) == "Super Mario 64 (Europe) (En,Fr,De)"


def test_title_match_prefers_the_roms_region_then_usa():
    assert artfind.best_match("super mario 64 [Japan]", names()) == "Super Mario 64 (USA)"  # no (Japan) tag
    assert artfind.best_match("Super Mario 64 (Japan) [!]", names()) == "Super Mario 64 (Japan)"
    assert artfind.best_match("Super Mario 64", names()) == "Super Mario 64 (USA)"


def test_articles_punctuation_and_betas():
    assert artfind.best_match("The Legend of Zelda - Ocarina of Time", names()) == \
        "Legend of Zelda, The - Ocarina of Time (USA)"
    assert artfind.best_match("Mario Kart 64", names()) == "Mario Kart 64 (USA)"
    assert artfind.best_match("Wave Race 64", names()) is None


def test_libretro_swaps_unsafe_characters():
    assert artfind.libretro_name("Q*bert: Hi/Lo?") == "Q_bert_ Hi_Lo_"


def test_listing_is_cached():
    net = Net()
    artfind.index("n64", "Named_Titles", net)
    artfind.index("n64", "Named_Titles", net)
    assert len(net.asked) == 1


def _rom(system, name, art=None):
    return Game(f"rom:{system}:{name}", name, system, ("x",), art=art)


def test_run_fetches_missing_art_and_library_finds_it(tmp_path):
    from pathlib import Path

    from hearth import library

    games = [_rom("n64", "Super Mario 64 (USA).z64"), _rom("n64", "Has Art.z64", art="/a.png"),
             _rom("pc", "Port.AppImage"), _rom("n64", "Nothing Like It.z64")]
    net = Net()
    assert artfind.run(games, fetch=net, sleep=lambda s: None) == 1
    path = artfind.found("n64", "Super Mario 64 (USA)")
    assert path and Path(path).read_bytes() == PNG
    assert library.rom_art("n64", Path("/roms/n64/Super Mario 64 (USA).z64")) == path
    # A game that wasn't found isn't asked for again for a while.
    net.asked.clear()
    artfind.run(games, fetch=net, sleep=lambda s: None)
    assert not any("Nothing" in u for u in net.asked)


def test_offline_stops_quietly():
    games = [_rom("n64", "Super Mario 64 (USA).z64")]
    assert artfind.run(games, fetch=Net(down=True), sleep=lambda s: None) == 0
    # ...and tries again next time: not recorded as a miss.
    assert artfind.run(games, fetch=Net(), sleep=lambda s: None) == 1


def test_urls_are_quoted():
    assert artfind._url("n64", "Named_Titles", "Mario Kart 64 (USA)") == \
        "https://thumbnails.libretro.com/Nintendo%20-%20Nintendo%2064/Named_Titles/Mario%20Kart%2064%20%28USA%29.png"


def test_a_missing_listing_is_remembered_not_refetched():
    import urllib.error

    asked = []

    def fetch(url):
        asked.append(url)
        raise urllib.error.HTTPError(url, 404, "nope", {}, None)

    assert artfind.index("saturn", "Named_Titles", fetch) == []
    assert artfind.index("saturn", "Named_Titles", fetch) == []
    assert len(asked) == 1

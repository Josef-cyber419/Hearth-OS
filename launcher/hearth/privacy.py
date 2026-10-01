"""Privacy: what Hearth sends (nothing about you), and turning off the TV's own
tracking.

Most smart TVs watch whatever is on screen, including games and films from
this PC over HDMI ("automatic content recognition", ACR), and sell what they
see to advertisers. Every maker hides the switch somewhere different; these
are the usual places. Menus move between models and years, so each guide also
says which words to look for.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TvGuide:
    key: str
    name: str
    steps: tuple[str, ...]
    look_for: str  # the words to search the TV's settings for, if the path differs
    matches: tuple[str, ...] = ()  # how the TV names itself over HDMI-CEC


GUIDES = (
    TvGuide("samsung", "Samsung",
            ("Settings > All Settings > General & Privacy > Terms & Privacy",
             "Turn off Viewing Information Services",
             "Turn off Interest-Based Advertisement and Voice Recognition Services"),
            "Viewing Information Services", ("samsung",)),
    TvGuide("lg", "LG",
            ("Settings > All Settings > General > System > Additional Settings",
             "Turn off Live Plus",
             "Then Support > Privacy & Terms > User Agreements: turn off Viewing Information and Interest-Based "
             "Recommendation"),
            "Live Plus, Viewing Information", ("lg",)),
    TvGuide("sony", "Sony",
            ("Settings > Privacy (or System > Initial setup > Samba Interactive TV)",
             "Turn off Samba Interactive TV",
             "In Google's settings: Privacy > Usage & Diagnostics off, and Ads > Opt out of Ads Personalization"),
            "Samba Interactive TV", ("sony",)),
    TvGuide("vizio", "Vizio",
            ("Settings > Admin & Privacy",
             "Turn off Viewing Data",
             "Turn off Advertising Personalization"),
            "Viewing Data", ("vizio",)),
    TvGuide("roku", "Roku TV (TCL, Hisense, Sharp and others)",
            ("Settings > Privacy > Smart TV Experience",
             "Turn off Use info from TV inputs",
             "Then Settings > Privacy > Advertising: turn on Limit ad tracking"),
            "Smart TV Experience", ("roku",)),
    TvGuide("hisense", "Hisense (VIDAA)",
            ("Settings > Support (or System) > Privacy",
             "Turn off Viewing Information Services (or Smart TV Experience)",
             "Turn off personalised ads"),
            "Viewing Information, Smart TV Experience", ("hisense",)),
    TvGuide("tcl", "TCL (Google TV)",
            ("Settings > Privacy",
             "Turn off any viewing or content recognition option (sometimes called Viewing Data or Samba TV)",
             "Then Ads > Opt out of Ads Personalization, and Usage & Diagnostics off"),
            "Viewing Data, Samba", ("tcl",)),
    TvGuide("philips", "Philips",
            ("Settings > Privacy (or General settings > Advanced)",
             "Turn off Samba Interactive TV or any viewing data option",
             "Then Ads > Opt out of Ads Personalization"),
            "Samba, Viewing data", ("philips",)),
    TvGuide("panasonic", "Panasonic",
            ("Settings > Network (or Setup) > Privacy / Data service",
             "Turn off any viewing data or data service option",
             "Turn off personalised ads"),
            "Data service, Viewing data", ("panasonic",)),
    TvGuide("other", "Other",
            ("Open the TV's settings and look for a Privacy or Terms section",
             "Turn off anything named viewing data or information, content recognition (ACR), Live Plus or Samba",
             "Turn off personalised or interest-based ads"),
            "Privacy, viewing data"),
)

BY_KEY = {g.key: g for g in GUIDES}

HEARTH_PROMISE = ("No ads, no sponsored tiles, and nothing sent about what you watch or play. "
                  "Hearth's logs and problem reports stay on this PC until you send one.")
WHAT_LEAVES = ("Update checks (GitHub), app installs (Flathub), names of emulated games that need a picture "
               "(libretro's thumbnails; off in Home screen settings), and whatever the apps and services you sign in "
               "to send themselves (Steam, YouTube...).")
WHY_TV = ("Most smart TVs watch what's on screen, games from this PC included, and sell it to advertisers. "
          "Off is quicker, too.")


def guide_for(vendor: str | None) -> TvGuide | None:
    """The guide for a TV that named itself `vendor` over HDMI-CEC."""
    if not vendor:
        return None
    words = vendor.lower().replace(",", " ").replace(".", " ").split()
    for g in GUIDES:
        if any(m in words for m in g.matches):
            return g
    return None

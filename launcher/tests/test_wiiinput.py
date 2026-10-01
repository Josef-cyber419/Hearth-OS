

def test_a_remote_lying_still_isnt_polled_fast():
    # Field report #48: 100 Hz all day with a remote connected cost 2.5% of a core.
    from hearth.wiiinput import WiiInput

    class Still(WiiInput):
        spot = (0.5, 0.5)
        active = True

        @property
        def pointer(self):
            return self.spot

    w = Still(None, lambda: None, lambda: None, find=lambda: [], dolphin=lambda: False)
    assert w.in_use(now=0.0)  # just connected
    assert w.in_use(now=2.0)
    assert not w.in_use(now=3.5)  # still for 3 s
    w.spot = (0.52, 0.5)
    assert w.in_use(now=4.0)  # picked up again

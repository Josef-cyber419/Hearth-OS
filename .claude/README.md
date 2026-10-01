# Claude Code settings for this checkout

`settings.json` pre-approves the read-only commands in docs/FIELD_TESTS.md
(hearthctl's checks, journalctl, xprop, `gh issue`...), so a field-test run
on the living-room PC carries on after the owner leaves. Anything that
changes the PC still asks, and the updater, rollback, sudo, bootc and the
power commands are refused outright. See CLAUDE.md.

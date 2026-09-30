# Progress reports

One report per version: numbers, what's working, what's new, open issues. Latest: **[0.23.0](0.23.0/report.md)**.

## History

Every version, counted from the code as it was released. Lines of code don't count blank lines; tests are the automated test functions; pull requests are those merged by then.

| Version | Date | Lines of code | Tests | Docs (lines) | Guides | Pull requests |
|---|---|--:|--:|--:|--:|--:|
| [0.23.0](0.23.0/report.md) | 2026-09-30 | 16,937 | 433 | 1,892 | 15 | 27 |
| [0.22.4](0.22.4/report.md) | 2026-09-30 | 15,485 | 381 | 1,773 | 14 | 27 |
| [0.22.2](0.22.2/report.md) | 2026-09-30 | 15,066 | 374 | 1,556 | 13 | 26 |
| [0.22.1](0.22.1/report.md) | 2026-09-30 | 15,008 | 370 | 1,548 | 13 | 25 |
| [0.22.0](0.22.0/report.md) | 2026-09-29 | 15,005 | 369 | 1,544 | 13 | 24 |
| [0.21.0](0.21.0/report.md) | 2026-09-29 | 13,506 | 334 | 1,371 | 11 | 23 |
| 0.20.0 | 2026-09-29 | 12,533 | 312 | 1,260 | 10 | 20 |
| 0.19.0 | 2026-09-29 | 11,984 | 291 | 1,120 | 9 | 19 |
| 0.18.0 | 2026-09-29 | 11,370 | 270 | 1,067 | 8 | 18 |
| [0.17.0](0.17.0/report.pdf) | 2026-09-29 | 11,288 | 268 | 1,034 | 8 | 17 |
| 0.16.0 | 2026-09-29 | 10,159 | 233 | 1,022 | 8 | 16 |
| 0.15.0 | 2026-09-29 | 9,817 | 223 | 971 | 7 | 15 |
| 0.14.0 | 2026-09-29 | 9,741 | 218 | 969 | 7 | 14 |
| 0.13.0 | 2026-09-29 | 9,507 | 205 | 954 | 7 | 13 |
| 0.12.0 | 2026-09-27 | 9,474 | 201 | 954 | 7 | 12 |
| 0.11.0 | 2026-09-27 | 9,339 | 195 | 953 | 7 | 11 |
| 0.10.0 | 2026-09-27 | 9,326 | 194 | 940 | 7 | 10 |
| 0.9.0 | 2026-09-27 | 9,111 | 179 | 906 | 7 | 9 |
| 0.8.0 | 2026-09-27 | 9,072 | 173 | 904 | 7 | 8 |
| 0.7.0 | 2026-09-27 | 8,970 | 165 | 901 | 7 | 7 |
| 0.6.0 | 2026-09-27 | 8,931 | 163 | 901 | 7 | 6 |
| 0.5.0 | 2026-09-27 | 8,836 | 157 | 897 | 7 | 5 |
| 0.4.0 | 2026-09-27 | 8,598 | 144 | 888 | 7 | 4 |
| 0.3.0 | 2026-09-27 | 8,597 | 141 | 886 | 7 | 3 |
| 0.2.0 | 2026-09-27 | 8,336 | 132 | 865 | 7 | 2 |
| 0.1.0 | 2026-09-25 | 4,155 | 66 | 703 | 7 | 1 |

## Making the next one

When `VERSION` goes up: update `reports/status.toml` (what's working, issues, next), put any screenshots in `reports/<version>/screens/`, then run

```sh
python3 tools/progress_report.py
```

It writes `reports/<version>/report.md` (and `report.pdf` when reportlab is installed) and this table.

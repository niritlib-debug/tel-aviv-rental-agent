# data branch

Memory of the rental agent, written by the `rental-agent` GitHub Actions workflow after every run.
Do not edit by hand. Design: [Architecture.md §4.3](https://github.com/niritlib-debug/tel-aviv-rental-agent/blob/main/Architecture.md).

- `rentals.db`: SQLite database (listings, listing_changes, runs)
- `reports/`: one Markdown report per run

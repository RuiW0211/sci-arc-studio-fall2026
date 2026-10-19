# 990 fetching tools

Written 2026-10-19 while continuing the museum-revenue research.

The earlier session hit two walls that turned out not to be walls:

- **ProPublica's API** was blocked by the Cowork sandbox proxy. It works from a normal
  machine with no key: `https://projects.propublica.org/nonprofits/api/v2/organizations/<EIN>.json`.
- **Full-text 990 pages** 302 to a signed S3 URL. The handoff said these "have to be opened
  in a real browser." They don't — `curl -sL --compressed` follows the redirect and returns
  the rendered HTML. The `--compressed` flag is the part that matters; without it you get gzip bytes.

## Usage

```bash
python3 fetch990.py <object_id> [form] ["start regex" "end regex"]
python3 fetch990.py 202630989349301143 IRS990 "Statement of Revenue" "Statement of Functional Expenses"
python3 objids.py <EIN>          # list that filer's object IDs, newest first
```

`form` is `IRS990`, `IRS990PF`, `IRS990ScheduleR`, `IRS990ScheduleG`, and so on.
Pages are cached next to the script as `<object_id>_<form>.html`.

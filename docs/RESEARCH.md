# Research database: verification rules and data format

`web/research/data.json` feeds the Research page (`web/research/`). Its purpose is that **every entry on the page is
current, true and traceable**, and secondarily that entries with a place and a time can later be shown in the site
viewer. Accuracy comes first: an entry that cannot be traced to a reliable source is marked as such, never padded.

These rules apply to everyone who edits the file, people and Claude sessions alike.

## 1. Verification rules

1. **No reliable source, no fact.** A statement goes in as `verified` only when a source that supports it has been
   opened and read. Never cite from a title, a search snippet, memory or another summary.
2. **The source must say it.** For each source, check that the page actually contains the claim (the date, the
   number, the wording). Record the access date (`accessed`) and, where useful, a short supporting excerpt
   (`excerpt`, at most about 25 words, quoted exactly).
3. **Source order.** Court records, statutes, government documents and board minutes first; then established news
   outlets; then secondary works (books, encyclopaedias, blogs). A secondary source alone gives `confidence: medium`
   at most.
4. **Leads are not evidence.** Earlier research files (`Y-1_V2_Complete_Research.md` and others, written with Claude)
   and the professor's *Initial Site Narrative (TBC)* (also AI-drafted, Sept 2026) are leads. Their statements are
   checked against the original sources before they count.
5. **Fact, claim or analysis.** `kind` says what a statement is: a `fact` (a court ruled on 11 March 2025), a `claim`
   (one party says the termination was political), or our own `analysis`. A claim is never written as a fact.
6. **Things that change carry a date.** Statuses (litigation, the Notice of Availability, a director's post) are
   written "as of" a date, and `lastVerified` records the day the entry was last checked against its sources.
7. **Disagreements are shown, not resolved silently.** When sources differ, list each in `conflicts`, say which one
   the entry follows and why.
8. **Not found is a result.** If something cannot be confirmed, say so and list where it was looked for. Never guess
   or make up a date, a figure, a link or a quotation.
9. **Unsupported entries are downgraded, not deleted.** An existing entry whose sources do not hold up becomes
   `unverified`, with the reason in `details`, so the search is not repeated.
10. **Copyright.** Summarise in our own words; quote only short passages, with attribution. No images or long
    extracts from press, archives or EIR appendices.
11. **Language.** The page is in English. Quotations stay in their original language; a non-English quotation gets an
    English translation (`translation`), kept neutral and faithful.

## 2. Entry format

```jsonc
{
  "id": "lit-002",                       // topic prefix + number; never reused
  "title": "…",
  "summary": "…",                        // one or two sentences
  "details": ["…"],                      // supporting points; say where a point comes from
  "topic": "Litigation",
  "date": "2024-02-13",                  // the event's date (YYYY, YYYY-MM or YYYY-MM-DD), null if none
  "kind": "fact",                        // fact | claim | analysis
  "status": "verified",                  // verified | unverified | analysis | open-question
  "confidence": "high",                  // high | medium | low
  "lastVerified": "2026-10-12",          // last check against the sources; null = not checked since import
  "place": ["parcel:Y-1"],               // where it happened (see below); [] if nowhere in particular
  "timeline": { "start": "2023-10-12", "end": "2024-02-13" },   // for a timeline; null if not a dated event
  "conflicts": [                         // optional: sources that disagree
    { "note": "Trade press gives April 2022", "sources": [0, 2] }
  ],
  "sources": [
    { "type": "court", "title": "…", "url": "…", "accessed": "2026-10-12", "excerpt": "…" }
  ],
  "sourceFile": "…"                      // optional: the research file the entry first came from
}
```

- **`place`** uses stable IDs: `parcel:Y-1`; `entity:E005` (an entity in
  `site-model/houdini/annotations/entities.json`, e.g. E005 Angels Flight); `object:MOCA` (a stable object name);
  `area:Bunker Hill`, `area:Grand Avenue` for districts. Numbered object names (`Tree_0042` …) are never used.
- **`timeline`**: `start` and `end` in the same date forms as `date`; `end: null` for a single moment, `"present"` for
  an ongoing state (e.g. the fence since July 2013).
- **`viewer`** (optional): one line on how the entry could appear in the site viewer (place + time), for later use.
- **`geometry`** (optional, unbuilt schemes): machine-readable figures for drawing a building in the viewer (floors,
  height in ft, position as the source describes it). Only numbers a source states; nothing estimated.
- **Source `type`**: `court`, `legal` (statutes, regulations), `official` (government, agency, board), `archival`,
  `news`, `secondary` (books, encyclopaedias, blogs), `social` (posts and comments), `analysis` (our own files).

## 3. Media entries (topic `Media`)

What people have said about the site: interviewees in the press, speakers at public meetings, officials, developers,
advocacy groups, and posts and comments on Reddit, YouTube and other platforms. A Media entry records **who said
what, where and when**; it is evidence of an opinion, never of a fact.

```jsonc
{
  "id": "media-001",
  "topic": "Media",
  "kind": "claim",
  "title": "…",                          // what the statement is about, neutral
  "summary": "…",                        // our neutral paraphrase
  "media": {
    "quote": "…",                        // verbatim, checked against the source; short
    "translation": null,                 // English, if the quote is not in English
    "speaker": "Reddit u/example",       // platform + user name, or name
    "role": "commenter",                 // e.g. councilmember, developer, resident, advocacy group, commenter
    "venue": "r/LosAngeles thread …",    // the article, meeting, video or thread
    "said": "2018-06-14",                // when it was said
    "subject": "Angels Knoll closure"    // the discussion it belongs to
  },
  "place": ["parcel:Y-1"], "timeline": { "start": "2018-06-14", "end": null },
  "status": "verified",                  // verified = the quote is exactly in the source
  "confidence": "high", "lastVerified": "2026-10-12",
  "sources": [ { "type": "social", "title": "…", "url": "…", "accessed": "2026-10-12" } ]
}
```

- Quotations are copied exactly; a shortened quote marks the cut with "…". If the wording cannot be checked, the entry
  is not added.
- Commenters are named as platform + user name, as the post shows it. Only public posts are used, and nothing else
  about the person is collected or combined.
- Pick statements that show a range of views on a subject, not only the loudest.

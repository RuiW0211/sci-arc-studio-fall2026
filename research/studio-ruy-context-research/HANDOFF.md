# STUDIO RUY context research: museum revenue and visitors

Rolling handoff. Started in a Claude (Cowork) session on 19 October 2026, continued in Claude Code
the same day. Part of the Syracuse Visiting Studio, Fall 2026 (Angel's Knoll / Bunker Hill Parcel Y-1,
Los Angeles). MOCA and the Broad are the site's direct neighbours on Grand Avenue.

**To pick this up:** open the repo and say *"Read research/studio-ruy-context-research/HANDOFF.md and
continue this research."*

---

## 1. Where things stand

| | |
|---|---|
| Branch | `clark/museum-economy`, cut from `origin/main` (PR #24) |
| Web page | `web/museums.html` + `web/js/museums.js`, reached by the arrow beside the viewer's title |
| Run it | `python3 web/serve.py 8769` then open `http://127.0.0.1:8769/museums.html` |
| Data | `museum_revenue.csv` (stale — see §6), the live figures are in `web/js/museums.js` |
| Tools | `tools/` — see `tools/README.md` |

**Do not** commit to `main`. CONTRIBUTING: branch → PR → Rui reviews → merge.

## 2. The question

Clark wants hard data comparing MOCA, the Broad, LACMA, MoMA, the de Young and the Petersen:
ticket sales, profit, visitor numbers, public preference, and how each makes its money as pie charts.
**Source rule from Clark: do not cite Wikipedia** — use it only to find primary sources. Prefer audited
statements, IRS Form 990s, annual reports, and reputable press.

## 3. Main findings

**None of these museums lives on ticket sales.** MoMA is the most self-funded and even there admissions
are about 15% of operating revenue, while its shops bring in twice as much. The LA museums run on donors,
plus county money at LACMA. The Petersen is the exception: admissions are its largest single stream.

**MOCA is an endowed institution with a museum attached.** Its $8,641,000 endowment draw is close to four
times its entire earned income (~$2.3M). Free admission since 2020, no food, no parking, no events
business, one small store.

**"Profit" depends entirely on basis.** MoMA FY2025 reads **+$56.8M** on the 990 and **−$32.3M** on the
audited operating statement — same museum, same year. Any profit chart must state its basis on its face.

| Museum | Basis | Revenue | Expenses | Result |
|---|---|---|---|---|
| MoMA FY2025 | 990 | $362.0M | $305.3M | **+$56.8M** |
| MoMA FY2025 | audited, operating | $282.8M | — | **−$32.3M** |
| LACMA FY2025 | 990 | $235.4M | $124.5M | **+$110.8M** (capital campaign gifts) |
| MOCA FY2025 | 990 | $29.6M | $26.5M | **+$3.0M** |
| Petersen CY2024 | 990 | $28.0M | $28.1M | **−$0.09M** |
| The Broad CY2024 | 990-PF | $27.8M | $29.6M | **−$1.8M** |

## 4. Two blockers from the first session that are NOT real

- **ProPublica's API** works from a normal machine, no key:
  `https://projects.propublica.org/nonprofits/api/v2/organizations/<EIN>.json`
- **Full-text 990s do not need a browser.** `curl -sL --compressed` follows the signed-S3 redirect.
  The `--compressed` flag is the whole trick. See `tools/fetch990.py`.

## 5. Revenue by stream, $ millions

Positive slices only; negative lines are listed under the table. Normalised so six museums compare.

| Museum | Period | Gifts | Gov't | Invest | Admis. | Member. | Shops/aux | Other | Shown | Reported |
|---|---|---|---|---|---|---|---|---|---|---|
| MoMA | FY2025 (Jun) | 66.9 | 0 | 64.1 | 42.4 | 14.7 | 86.5 | 8.2 | 282.8 | 282.8 |
| LACMA | FY2025 (Jun) | 121.2 | 36.7 | 52.4 | 4.3 | 3.4 | 1.5 | 49.0 | 268.5 | 266.5 |
| de Young + Legion | FY2025 (Jun) | 33.8 | 21.4 | 4.8 | 6.9 | 11.7 | 3.1 | 2.4 | 84.1 | 84.1 |
| MOCA | FY2025 (Jun) | 21.107 | 0.150 | **6.519** | 0.834 | 0.911 | 0.448 | **0.811** | 30.78 | 29.6 |
| The Broad | CY2024 | 10.741 | 0 | 1.242 | 1.025 | 0 | 3.952 | 12.725 | 29.69 | 27.8 |
| Petersen | CY2024 | 8.312 | 0 | 1.638 | 9.782 | 2.202 | 4.388 | 2.218 | 28.54 | 28.0 |

Excluded negatives: LACMA −$2.0M swap; MOCA −$1.22M net fundraising events; the Broad −$1.88M asset
sales; Petersen −$0.40M events and −$0.15M asset sales.

### Corrections to the first session's numbers

- **MOCA membership is broken out** on line 1b — $910,993. The first handoff said it wasn't.
- **MOCA government is not zero** — $150,291 on line 1e (down from $592,690 in FY2024).
- **MOCA admissions are $833,856**, not $1.0M; the $1,040,114 was all program service revenue, which also
  holds travelling exhibition fees ($200,000), workshop and reproduction fees.
- **MOCA investment now carries the $4,783,772 realised gain**, moved out of "other". The 990 separates
  them only because gains sit on line 7. Other drops from 5.594 to 0.811.
- **The Broad's "$2M gap" is gone.** It was gross rents ($454,813) plus a shop line the handoff thought
  wasn't itemised. Everything reconciles to $27,800,063 exactly.
- **The Broad does report ticket revenue** — $1,024,889 of exhibits and ticketed programmes, Part XV-A.

## 6. `museum_revenue.csv` is STALE

It still holds the pre-correction MOCA and Broad rows and the old category split. **The live figures are
in `web/js/museums.js`** (`MUSEUMS`). Either regenerate the CSV from that or delete it — do not cite it.

## 7. Per-museum detail

### MOCA (worked through in depth)
- **Endowment $181,127,729.** Earned $13.25M in the year, of which $8.02M unrealised and never on the 990.
  Drew **$8,641,000**. **0% board-designated**, 70.8% permanent, 29.2% term — most cannot be spent down.
  Held as $106.5M commingled, $28.7M private, $27.6M alternatives.
- **Audited revenue $36,912,441 vs 990 $29,554,913** — the gap is unrealised gains (Schedule D Part XI).
- **Gifts nearly doubled in 5 years:** $12.02M, $12.91M, $12.95M, $18.03M, $22.17M. Public support 85.8%,
  up from 76.8%. Donors over the 2% threshold gave $3.74M in excess.
- **Noncash:** 14 works of art (no revenue value) and $669,447 of publicly traded securities.
- **"Other income" $434,804 is unexplained.** Schedule O is governance only; Schedule A asks for it to be
  itemised in Part VI, which was left as boilerplate. Trend: $139K, $78K, $217K, $204K, $435K.
- **Shops is one line only** — Part VIII line 10, the store. $887,343 gross, $439,024 cost of goods,
  $448,319 net. Zero occurrences anywhere in the return of café, restaurant, food, dining, parking, store,
  retail, bookstore or merchandise. The only "shop" hit is *workshop fees*, $3,374.
- **Schedule F is investments only** — zero offices and zero employees in every region; $99.4M sits in
  Caribbean-domiciled funds. That also explains the $47,265 of UBTI with $0 unrelated revenue (K-1s).
- Spent **$4,579,563 on art**, expensed not capitalised (Schedule O).

### MOCA's buildings — resolved
- **Grand Avenue: MOCA owns it.** The CRA's 1980 California Plaza RFP *required* bidders to include a
  modern art museum. Bunker Hill Associates won and built MOCA (~$23M) as the price of an 11-acre public
  parcel. MOCA held the land on a **1983 CRA lease, 99 years, no rent**, and in **October 2015 the CRA sold
  it to MOCA for $100,000**. Corroborated by the balance sheet: Land **$100,000** exactly; Buildings
  $25,367,304 cost, depreciated to $1,441,753.
- **The Geffen Contemporary: leased, not owned.** 1947 Union Hardware warehouse, later city-used, Gehry
  renovation, opened 1983 as the Temporary Contemporary, renamed 1996 after a $5M Geffen gift. The tell is
  **$9,913,000 of leasehold improvements** — you do not capitalise those on property you own. The landlord
  and rent are **not** in the filing and were not confirmed from public records.
- Dead end: the 2005 CRA report in search results is the **Grand Avenue Project** (Related Companies), a
  different deal. Next step: City Clerk files on the 2015 CRA/LA disposition, or the Assessor's record.

### LACMA
- **$36,723,000 is not a grant.** Museum Associates operates a museum the **County owns, on County land,
  under contract**; the 990 books it as program service revenue on line 2a. Separately $1,360,174 of
  ordinary government grants, which sit inside gifts on the audited basis.
- **$40,897,833 of "all other program service revenue" is unitemised** on the 990 and unexplained in
  Schedule O. Program service revenue jumped $45.3M → $87.2M, a $41.9M swing matching it almost exactly,
  consistent with the insurance settlement the audited statements mention — *but the filing never says so*.
- Also broken out: parking $3,421,711, exhibition revenue $952,958, special projects $487,622, food
  services $152,765, net shop $751,564, admissions $4,674,131 (990 basis).
- **Endowment $195,362,701** — but **47.9% board-designated**, 21.9% permanent. Draw $8,654,158.
  Near-identical draw to MOCA's on a similar pot, but far more of it is spendable.

### MoMA
- **The shops slice is retail, not dining.** Gross inventory sales **$83,305,522**; restaurants only
  **$1,366,179**, filed under the *food service contractors* code; corporate events $2,263,124.
- **Schedule R lists no restaurant entity** — only MoMA Auxiliaries ("Manage Retail Operation") and
  **Alta Cultura**, a wholly-owned taxable C corp. Evidence points to contractor-operated dining.
- Admissions $41,968,406 on the 990; adult ticket $30 since 2023; ~2.8M visitors 2025 ≈ $15/visitor.

### The Broad
- "Other income" $15,701,078 decomposes exactly: **GAAP discount on pledges $11,630,844**, museum parking
  $2,406,170, exhibits and ticketed programmes $1,024,889, program-related services $600,000,
  reimbursements $37,175, advertising $2,000. **The largest line is an accounting entry, not cash.**
- Shop: $3,338,377 gross, $1,792,767 cost of goods, $1,545,610 gross profit.

### Petersen
- Admissions **$9,781,917** — the only museum here where tickets lead. Membership dues $1,949,466 plus
  $253,030 of membership events. Parking $2,902,316 (of which $1,037,790 taxed as UBI). Rents $2,132,347,
  purpose not stated. Shop $2,865,365 gross, $1,485,910 net.

### FAMSF — the biggest hole
- **No 990 has been pulled.** COFAM, EIN **94-3045948**, latest object **202611339349306916**, FY2025
  revenue **$53,329,543**. The pie uses **$84.1M** from the annual report, which covers the combined
  institution (City department + nonprofit). **The de Young slice may be on a different basis than the
  other five.** Resolve before this goes to Clark.

## 8. Attendance

- **MoMA** ~2.8M in 2025, up 4% (Art Newspaper). **FAMSF** 1,246,838 across both sites; Legion 406,265.
- **The Broad, derived from its own 990-PFs** (each states cumulative visitors; deltas give the year).
  Source figures are rounded, so ±~50k: **2021 ~200k, 2022 ~640k, 2023 ~900k, 2024 ~820k.**
  Cumulative "nearly 6.2M through 2024" — the press's 6.7M is through the 10-year mark in Sept 2025.
- **The Art Newspaper's 2025 survey excludes LACMA, the Broad, MOCA and the Petersen.** Confirmed — do not
  search it again. Neither MOCA's nor the Petersen's 990 states attendance in Part III.
- LACMA, MOCA, Petersen current attendance: **still open.**

## 9. The gala "loss"

The IRS splits a gala: the part of a ticket above what guests received is a donation (line 1c); only the
remainder goes on the event line (8a), and all direct costs come off that. Galas therefore read as losses.
MOCA FY2025: $3,076,298 gross, $2,923,874 to donations, −$1,224,600 reported, about **+$1.70M** in truth.
Petersen 2024: $3,183,559 gross, $2,026,459 to donations, −$404,205 reported, about **+$1.62M**.

## 10. The web page

Four scroll-snapped panes: **intro → pies → mocaPane → tablePane**.

- **Intro** — title, sources, "each dot corresponds to $100,000.00", a Scroll button.
- **Pies** — six discs on one canvas, drifting points, no legend and no labels. Hover gives the total and
  the stream under the cursor, and dims the other wedges to 28%. Clicking a stream with a breakdown
  **regroups its points** over 2 seconds: that wedge's own points detach and fly into the breakdown, each
  travelling from where it sat to where it belongs, colour easing from the parent's shade to its part's,
  while the rest of the field eases back to 1.9× and dims. Click outside or press Escape.
  Grid order is fixed by `GRID`: MOCA · LACMA · The Broad over MoMA · Petersen · de Young.
- **mocaPane** — MOCA alone. The right half previews the stream under the cursor (name and amount);
  clicking writes its full detail there as prose and bullets, and hovering elsewhere then leaves that
  detail alone. Shops carries the full "what it does not include" list.
- **tablePane** — the same figures with the caveats.

### Design decisions worth not re-litigating
- **One point = $100,000**, same size at the same density everywhere, so **disc area is proportional to
  revenue** automatically. Do not scale discs by hand.
- **Palette is one neon-blue family**, seven steps `#10498C` → `#B5E4FF`. Steps are ≥0.062 apart in OKLCH
  lightness and the darkest clears 2:1 on black. Wedge order interleaves the ramp so touching wedges sit
  far apart (worst adjacent ΔE 25.3). Reproduce with `tools/ramp.py`; validate with `tools/valpal.py`.
- Points sit on a **Vogel spiral sorted by angle**, cut into contiguous runs — that is what gives the
  wedges soft edges. Seeded, so the layout is identical every load.
- **The regroup is 1:1 where the counts allow it.** Nine of the thirteen breakdowns have exactly as many
  points as their parent wedge; the four that differ (MoMA shops +4, LACMA government +14 and other −30,
  MOCA other +1) are the ones drawn from a different basis than their parent, and those few points fade
  in or out mid-flight so the discrepancy stays visible.
- **`drawDisc`'s `dim` argument is a slot index, and −1 means none.** Never 0 — slot 0 is gifts and
  grants, and testing it for truthiness is the bug that stopped that one stream dimming the others.

### Known issues
1. **Gross vs net is inconsistent across the six.** MoMA's shops slice is **gross** ($83.3M before cost of
   goods); MOCA's, the Broad's and the Petersen's are **net**. MOCA's store on a gross basis is $887,343,
   about double what the pie shows. Pick one basis. Unresolved.
2. **No legend and no labels**, so stream identity rests on hover. The table is the fallback. Fine on a
   screen, a problem on a projector.
3. LACMA and the de Young have **no drill-downs** — neither source itemises in a way that sums to its
   parent. Deliberate; do not invent splits.
4. `museum_revenue.csv` is stale (§6).

### Where it can be seen
The repo is public, so the branch is readable by anyone. The **page is not live**: `.github/workflows/pages.yml`
builds only on a push to `main`, and `web/museums.html` exists only on this branch, so
`https://ruiw0211.github.io/sci-arc-studio-fall2026/museums.html` returns 404. A link someone can use needs
the work merged to `main` (Rui), or a manual `workflow_dispatch` run. **No PR has been opened yet** — that
decision was still open when this was written.

## 11. Open threads

1. **FAMSF's 990** (§7) — biggest gap, and it may invalidate the de Young slice's basis.
2. Settle the gross/net inconsistency (§10, issue 1).
3. Attendance for LACMA, MOCA, the Petersen (§8).
4. MOCA's Geffen lease — City Clerk files on the 2015 CRA/LA disposition, or the Assessor's record.
5. Schedule D endowments for MoMA, FAMSF and the Petersen, to finish the endowment table.
6. Schedule J officer compensation across all six.
7. MoMA's Schedule F and **Alta Cultura's own returns** — probably where the Tokyo and Seoul stores sit.
8. **The Broad Art Foundation**, a separate entity from the Broad.
9. The **990-T** returns the Broad and the Petersen both filed.
10. Public preference — no head-to-head survey found. Possible proxies: attendance, member counts, review
    counts. Google and TripAdvisor both resist scraping; Culture Track or IMPACTS may have a visitor survey.
11. Revenue per visitor, once attendance exists for more than three of them.

## 12. EINs and object IDs

| Filer | EIN | Latest object |
|---|---|---|
| MoMA | 13-1624100 | 202631339349300538 |
| MOCA | 95-3433820 | 202630989349301143 (FY2024: 202501209349301420) |
| The Broad | 27-3032164 | 202533209349101003 (CY2023: 202443179349103214) |
| Petersen | 95-4739699 | 202502389349301235 |
| LACMA (Museum Associates) | 95-2264067 | 202621339349308237 |
| COFAM (FAMSF) | 94-3045948 | 202611339349306916 |

`tools/objids.py <EIN>` lists a filer's object IDs newest first.

## 13. Sources

Audited and official:
- MoMA FY2025 statements — https://production-gcp.moma.org/docs/about/MoMAFY_25.pdf
- LACMA FY2025 statements — https://www-images.lacma.org/s3fs-public/2025-10/FS-LACMA-063025-Final-Signed.pdf
- FAMSF annual report FY2025 — https://www.famsf.org/storage/files/01be7936-63cf-4726-9fbd-e2dde72f5282/famsf-annual-report-WS26.pdf
- FAMSF commission minutes, April 2026 — https://media.api.sf.gov/documents/04.15.26_DRAFT_FAMSF_Mintues.pdf
- IRS filings via ProPublica — `https://projects.propublica.org/nonprofits/organizations/<EIN>`

Press (Clark's rule: no Wikipedia as a citation):
- Art Newspaper, 2025 visitor survey — https://www.theartnewspaper.com/2026/03/31/exclusive-the-worlds-100-most-visited-museums-in-2025-new-museums-a-big-hit-with-visitors
- Art Newspaper, LA free museum capital (2019 attendance) — https://www.theartnewspaper.com/2020/04/13/why-los-angeles-is-americas-free-museum-capital
- Bisnow, former Angels Landing site — https://www.bisnow.com/los-angeles/news/construction-development/downtowns-former-angels-landing-site-could-be-on-the-auction-block-soon-132018
- Urbanize LA, Angels Knoll tag — https://la.urbanize.city/tags/angels-knoll

**Unverified / treat with care:** the MOCA Grand Avenue lease history and the 2015 $100,000 sale came from
search summaries citing a MacArthur Foundation page; the balance sheet corroborates the $100,000 but the
deed has not been read. The Geffen lease extension "beyond 2040" is from a low-authority travel site.
MoMA's restaurant arrangement is inferred from the business code and Schedule R, not stated anywhere.

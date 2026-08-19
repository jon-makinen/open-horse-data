# open-horse-data

Real racehorses and their pedigrees, built from twelve public sources into one
CSV. It uses only the Python 3 standard library, so there is nothing to
install.

**The CSV is not in this repo, you build it.** That is deliberate: the output
is a derivative of whichever sources you fetch and it inherits their terms, so
there is no one file that is correct for everybody to hand out. Running the
commands below takes about an hour, most of it downloading.

A full build is **591,887 horses across 37 countries**, one row each, 24
columns, a single header row. 104,419 of them are broodmares who never raced,
carried so pedigrees do not dead-end after one generation. They have no race
record, so `Sex` is `F` and `Starts` is empty; that filter also catches 31,424
raced-elsewhere mares whose starts are simply unknown. Their `Foaled` year is
estimated from their first known foal and can be several years late. Dropping
the two archives that cannot be redistributed (see LICENSE) gives 489,355
horses instead.

## Run it

    python3 fetch_wikidata.py        # ~4 min
    python3 fetch_wikipedia.py       # a few minutes
    python3 fetch_ja_wikipedia.py    # a few minutes
    python3 fetch_tjk.py --pages 0   # 25-40 min
    python3 fetch_kra.py             # ~2.5 min
    python3 fetch_hkjc.py            # 12-15 min
    python3 fetch_ifha.py            # ~2.5 min
    python3 fetch_deltaromeo.py      # 1.1 GB
    python3 fetch_nar.py             # 182 MB
    python3 fetch_kaggle.py          # 248 MB, optional
    python3 build_csv.py

Output is `out/horses.csv`, about 92 MB. Fetching and building are separate,
so you can rebuild offline as often as you like, and any missing file in `raw/`
is simply skipped, which is how you opt out of a source.

Google Sheets caps a spreadsheet at 10 million cells, which the full build
passes on row count alone. `make_sheets_csv.py` cuts it to what will open:

    python3 make_sheets_csv.py    # out/horses_sheets.csv, 368,943 rows, 54 MB

It keeps every horse rated 70 or better and every ancestor behind them, so no
pedigree dead-ends mid-tree. Turkey is left out because TJK ratings are their
own scale and one threshold cannot judge both. 36 of the 38 countries survive.
It is a convenience copy, not the dataset; the full file is a rebuild away.

    python3 parsers.py                            # self-check
    python3 build_csv.py --max-per-country 8000   # even country mix
    python3 build_csv.py --all-breeds             # keep Arabians
    python3 build_csv.py --plain-names            # drop country suffixes
    python3 build_csv.py --leave-unrated          # blank instead of derived
    python3 build_csv.py --no-modelled-colours    # blank colour

Two files must be downloaded by hand, because both sites forbid automated
collection:

    BHA ratings database                     -> raw/bha.csv
    https://www.hri-ras.ie/full-flat-ratings -> raw/hri_flat.html
    https://www.hri-ras.ie/full-nh-ratings   -> raw/hri_nh.html

## Sources

| Source | Licence | What it gives |
| --- | --- | --- |
| Wikidata | CC0 | The pedigree spine. Sires are themselves rows, so trees chain 31 generations deep. |
| English Wikipedia | CC BY-SA | Dam, colour, owner, record, earnings for ~5,800 notable horses. |
| Japanese Wikipedia | CC BY-SA | ~5,700 Japanese horses, with a romanised English name in the infobox. |
| BHA ratings | manual download | ~11,900 British horses: sire, dam, sex, official rating. |
| Horse Racing Ireland | manual download | 5,056 Irish horses, same shape as the BHA file. |
| TJK (Turkey) | no robots.txt, no terms page | 113,000 horses with sire, dam, damsire, colour, country. |
| KRA (Korea) | KOGL Type 0 | Six registers, 34,000 rows, including gelding and retirement registers. |
| HKJC (Hong Kong) | no robots.txt, no scraping clause | 1,258 horses, the richest single page of any source. |
| IFHA rankings | robots.txt allows all | ~2,500 horses rated 115+, on one scale worldwide. |
| deltaromeo archive | CDLA-Sharing-1.0 | 1988-2026, 340,000 UK and Irish horses with sire, dam, damsire, sex, owner, rating, prize money. |
| ayuser archive | none stated | 2010-2021 Japan, ~90,600 horses. The only reachable Japanese source with pedigree. |
| hwaitt archive | CC BY-NC 4.0 | 1990-2020 UK results. Mostly superseded by deltaromeo. |

Ten of these can be used for anything. The exceptions are hwaitt, which is
non-commercial, and ayuser, which states no licence at all. Deleting those two
zips leaves a build that is clean for commercial use.

Race results are facts and are not copyrightable, but ratings are somebody's
opinion, so they are treated more carefully. Only official marks are read, and
Racing Post's RPR and Topspeed columns are ignored everywhere they appear.

### Not used

Blocked by licence: JBIS and JRA-VAN, equineline, Timeform, Racing Post, Racing
Australia, France Galop, LeTrot, Equibase, USTA, AQHA.

Missing the fields that matter: Betfair price files and gdaley/hkracing carry
no horse details, the latter removing horse names on purpose. takamotoki is Japanese race
results with no pedigree and no English names.

## The columns

24 columns. Four of them say where a value came from, because most of this file
is derived rather than measured. `Damsire` is the dam's own sire, the third name
on a racecard pedigree line.

| Column | Values |
| --- | --- |
| `Rating Scale` | `BHA` published, `TJK` published Turkish, `Estimated` from the horse's record, `Pedigree` from its parents, `Random` drawn from the real population up to 90, for horses with no record |
| `Colour Source` | `data` for 46,538 horses, `modelled` for the rest |
| `Distance Source` | `raced` where the horse actually ran, `category` from a rankings distance band, `pedigree` inherited |
| `Earnings Source` | `summed` from per-race prizes, `published` from a career figure |

Filtering on these gives a measured-only subset: 46,538 horses have a real
colour, 179,794 a real rating, 412,990 a distance from their own races.


Names are written the way a racecard writes them, `Frankel (GB)`,
`Galileo (IRE)`. Sire, Dam and Damsire use the same form, so the pedigree chain
resolves by plain name match and every name in the file is unique. Racing names are only
unique within a studbook, so without the country a Turkish colt called Abstract
and an Irish one are the same horse.

## Ratings

Every horse has a rating, and the `Rating Scale` column says where it came
from.

| Scale | Count | What it means |
| --- | ---: | --- |
| `BHA` | 160,500 | A published mark. British, Irish, IFHA, Hong Kong, or an archive's official rating. All on the same pound scale, so they compare directly. |
| `Estimated` | 261,600 | Worked out from the horse's own race record. |
| `Pedigree` | 66,400 | Worked out from its parents. |
| `Random` | 84,100 | Drawn from the real population, for horses with nothing else. |
| `TJK` | 19,000 | A published Turkish mark. Its own scale, not the pound scale. |

Turkish marks sit on a different distribution: median 35 against 72, and only
96 of 19,283 horses above 110. The top of each scale is similar but the shape
is not, so there is no offset that lines them up. Name matching does not help
either, since the 105 Turkish names that also appear in the world rankings
correlate at 0.11 with their rankings, meaning they are different horses sharing
a name.

Hong Kong marks are labelled `BHA` because nine Hong Kong horses also hold IFHA
rankings and the two figures differ by about 3 points.

**Estimated** ranks a horse by strike rate against all the other horses being
estimated, then lays that ranking onto the spread of horses that hold a real
mark. Looking each horse up by its strike rate directly was worse, because the
two groups do not run the same strike rates: it put ten times too many horses
at 130 and above. Matching on rank instead reproduces the real spread, 0.045%
at 130 or better against 0.045% in the published marks.

Horses on the same strike rate are ordered at random within that block, which
is also what stops the file collapsing. Every horse with one start and no wins
scores the same, and handing that whole block one rating once put a third of
the file in a single ten point band.

**Pedigree** uses the breeder's equation, `mean + h² × (midparent − mean)`, with
h² of 0.35, halved when only one parent is known. Spread is added back here too.
Regression gives the best guess for one horse and the wrong answer for a whole
population.

**Random** draws from the official ratings in the race archives rather than from
this file's own ratings, since a horse only carries a published mark if it was
good enough to be handicapped or written about. Sampling this file's own pool
put 29% of unknown horses at Group class.

That pool is then capped at 70. These horses have no record in any of the twelve
sources, and anything much better than modest would have left a trace somewhere,
so they run from 1 to 70 with a median of 60.

Jumps ratings are excluded, because a chaser runs to 180 where the best flat
horse in the world is 140. Anything above 142 is rejected.

## Coat colour

Only about 9% of horses came with a real colour. Every studbook that publishes
colour at scale is blocked by licence, so the rest are bred.

The inheritance table is measured from the 26,000 foal and sire pairs already in
the file. It comes out matching the textbook without being told to:

| Sire | Foals |
| --- | --- |
| Bay | 77% bay, 15% chestnut |
| Chestnut | 47% chestnut, 45% bay |
| Grey | 48% grey |
| Black | 15% black |

Grey is handled on its own, because it is a single dominant gene. A horse is
grey only if a parent is grey, and about half the foals of a grey parent are
grey. Grey is also worked out upwards, since a grey foal proves a grey parent.
Treating grey as just another colour in the table gave 11.6% grey overall
against a real 5%, while grey sires threw only 21% grey instead of 48%.

Horses are filled oldest first, so a bred sire passes colour to its own foals.
Real colours are never overwritten.

Seal Brown comes out at 4.6% against a real 15%, because sources record dark bay
as plain bay. The model copies its input rather than being corrected to match
the real world.

## Distance and surface

Both come from the race archives rather than a studbook.

Distances are imperial in the British and Irish data, `1m2f` or `1m½f`, and
metric in Japan. Best Distance is the average distance a horse actually won
over, falling back to where it ran if it never won. A horse that only won over
five furlongs is a sprinter whatever else it contested.

Surface comes from the going and the course name. `(AW)` in a course name means
all-weather. Turf is described by how soft it is, Good or Soft or Heavy. Dirt is
described by how fast it is, Fast or Sloppy or Muddy. Japan states it outright.
A horse gets whichever surface it raced on most.

`Standard` is the all-weather term in Britain, but abroad the same word just
means the dirt track is normal. Reading it as all-weather everywhere made
Hipodromo Chile, an all dirt oval, come out 100% synthetic, and Uruguay 74%.
Only the courses that really do have a synthetic track count, which is the
British all-weather tracks plus Deauville, Chantilly, Cagnes-sur-Mer and
Meydan.

Horses with no race record inherit a distance from their parents, using the
same equation as the ratings, so the offspring of stayers tend to stay. Derived
distances round to the nearest 100m, since a figure to the metre would suggest
more precision than there is.

Coverage is 92% for distance and 85% for surface. Galileo comes out at 2414m,
matching his real trip, and Flightline at 2000m on dirt.

## Earnings

Summed from prize money per race. deltaromeo's `prize` is what that horse won in
that race. Japan's `prize1` to `prize5` are the race prizes by finishing
position. A horse that earned in several currencies is reported in whichever it
earned most. Amounts are plain integers with no separators.

Coverage is 61%. Frankel comes to £2,998,302 and Deep Impact to ¥1,454,551,000,
both matching their real figures.

## Names

Japanese names resolve three ways: the horse's JBIS id joined to Wikidata, then
the Japanese Wikipedia crosswalk, then Hepburn romanisation of the katakana.
Famous horses have English loanword names and resolve by the first two, so
romanisation lands mostly on Japanese names where it reads correctly.

Korean names are all Hangul with no English form in the registers, so they use
Revised Romanization. These are readable approximations, not official names.

Japanese owner names are kanji. Kanji readings are ambiguous and cannot be
romanised by rule, so non-Latin owners are cleared.

## Data quality

`sanity_pass` clears impossible values on every build and prints what it
cleared: parents too young to have bred the foal (a sire must be three years
older) or a dam over 28, female or gelded sires, male dams,
placings above starts, and rows whose name is a placeholder for an unnamed
foal.

A parent that fails one of those checks is treated as a bad MATCH rather than a
bad name. A mare cannot foal at two, so the name found the wrong row, not the
wrong mare. The link is dropped and the name kept, and the country the source
declared is written into it, so `Music` becomes `Music (NZ)` and stops
resolving to the British Music. The name is only deleted when no country was
declared, because then there is nothing left to tell the two apart. Clearing
names instead used to discard about 46,000 real parents per build.

Nearly all of it comes back to one thing. Names are not unique. Every join
between sources needs a second key, and foaling year is the one nearly always
available. Without it a British horse gave the Japanese Deep Impact a rating of
88, and a modern Turkish horse made Eclipse, foaled 1764, Turkish.

Known gaps:

- **Starts, Wins, 2nds and 3rds are what these sources saw, not a career
  total.** The race archives are British, Irish, Japanese, Turkish and Korean,
  so a horse that raced mostly elsewhere is counted only for the runs it made
  here. Median recorded starts are 15 in Japan, 8 in England and 7 in Ireland,
  against 2 in Australia, Argentina, Brazil, Chile and Italy. 45% of Argentine
  and Chilean horses show exactly one start, and 38% of Australian ones. Spot
  checks bear it out: Aspenado shows 1 start and really ran 31, Blue Brigade
  shows 11 and really ran 39. Ratings are not distorted by this, because
  `_career_score` shrinks by sample size and a one-start record barely moves off
  the population mean, but do not read the record columns as a career.
- Punctuation and particle case are not part of a name, so `T.M. Opera O` and
  `T M Opera O` are folded into one horse. What survives is the spelling the
  rest of the file already points at, which keeps the most pedigree links: 163
  rows call him T M Opera O and none call him T.M. Opera O.
- Japanese horses can still appear twice under a registered English name and a
  Hepburn romanisation of the katakana, `A Shin Balancer` beside
  `Eishinbaransa`. Around 619 pairs remain. Folding those needs the Japanese
  name lookup this project does not have, so they are left rather than guessed.
- 82% of horses were foaled after 2000.
- Korea is 20% sire and dam, against 90% elsewhere. Most Korean rows come from a
  retirement register with no parentage, and Korea publishes no ratings.
- Turkey shows no geldings. Its register only records male and female.
- Broodmare rows are assembled from their produce, not measured. Every source
  here records horses that RAN, so a mare who raced twice or never never appears
  as a runner. Her foals name her, the source declares her country, and the
  Damsire column on her foals is her own sire, so the row is real apart from
  Foaled, which is her first known foal's year minus six. Six is the median gap
  among the 59,826 mares who do have a proper row. It reads late for a real
  first foal, because only foals that raced are visible here. The subtraction
  varies with how many of her foals turn up, 7 years when one or two do and 5
  when nine or more do, but it only corrects by a year or two. Where her early
  produce is missing entirely the year still lands late: Dance Attendance reads
  2001 and was foaled 1987. Treat it as a placeholder, not a fact.
- A mare is skipped when a horse that ran already uses her name, since two rows
  sharing a name would let a foal reach the wrong dam. That is 15% of them.
- Dam chaining is 89%, against 77% for sires and 72% for damsires. Before the
  broodmare rows it was 38%.

## What is in the repo

Code only. `raw/` and `out/` are both ignored, apart from the two files that
must be downloaded by hand because their sites forbid automated collection.
Everything else has a `fetch_*.py` that rebuilds it.

The built CSV is deliberately absent. It is a derivative of its inputs, some of
which cannot be redistributed at all, so shipping one file would hand everybody
the same licence problem. Build the mix you are allowed to use, and read LICENSE
before republishing it.

## A note on how this was built

This was put together with a lot of help from AI, over one long session. The
numbers in this README were measured from the built file rather than guessed,
and the checks in `parsers.py` run on every build, but that is not the same
thing as the data being correct.

Five independent audits were run over the finished file and each one found real
errors, several of which had been silently wrong for a long time. The known
remaining problems are listed under Known gaps above; the largest is that 91% of Japanese
names are phonetic romanisations of the katakana rather than the official
English names, which cannot be fixed without a licence-blocked source.

There are almost certainly more errors still in it. The ones that were found were
found by spot-checking rather than by any test: Eclipse, foaled 1764, had been
listed as Turkish because a modern Turkish horse shares the name; the Japanese
Deep Impact had been given a British horse's rating of 88; and ratings ran up to
180 because steeplechase marks leaked into a flat dataset three separate times,
by a different route each time.

Most problems trace back to the same thing, which is that horse names are only
unique within a studbook, so two different horses sharing a name can end up
merged into one row. If something looks wrong, that is the first place to look.

The derived columns are the least reliable. Rating, colour and best distance are
modelled for most horses rather than measured, and should be treated as
plausible rather than true.

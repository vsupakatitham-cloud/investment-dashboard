# Morning Brief — daily task

The Claude cloud routine "Morning brief (cloud)" runs this every day at 05:45 Bangkok time,
right after the 05:30 dashboard refresh, so the Brief tab of
https://vsupakatitham-cloud.github.io/investment-dashboard/ is ready by 06:30, before Korea
opens. You read the news that affects the portfolio's holdings, write a short brief, check
it and publish it. Work in the repository checkout; every path below is relative to its root.

## Rules that never bend

1. **Sources.** Use only domains listed in pipeline/news/sources.json under `tiers`. Never
   cite, search or fetch a `blocked` or `never` domain: Reuters, AP, Yonhap, AFP, the FT,
   WSJ, Barron's, MarketWatch, The Economist, BBC, NYT, The Guardian, social media, forums,
   blogs, video, contributor sites and aggregators. Never route around a block or a paywall:
   no proxies, caches, archive copies, mirrors or scrapers.
2. **Facts.** Every number comes from context.json or from a source you read in this run.
   When sources disagree, show both and set `verify` to `differ`. Never fill a gap from memory.
3. **Primary.** Set `"primary": true` only on an official document you actually checked: a
   central-bank or regulator statement, an exchange or SEC filing, a company or fund-house
   release.
4. **Your own words.** No quotation longer than 12 words, no copied headlines, no links or
   markup inside text fields.
5. **No advice.** Explain what happened and why it matters to these holdings. Never say buy,
   sell, hold, trim, add, accumulate, price target or "you should".
6. **Plain, calm English.** Short sentences. A reader should finish the 60-second brief in a
   minute.

## Command discipline

The run is unattended. From the repository root, use only these commands, one per Bash
call, exactly as written:

    bash scripts/morning_brief.sh prepare
    bash scripts/morning_brief.sh check
    bash scripts/morning_brief.sh publish

Read files with the Read tool. Write the draft with the Write tool to
news_work/<today>/draft.json (today = the Bangkok date; prepare prints the folder). Don't
edit any other file, and don't commit or push by hand: publish does both. If you need
something these commands don't cover, stop and say so in the report.

## Steps

1. **Prepare.** Run the prepare command. It pulls the repo and writes
   news_work/<today>/context.json, then prints a summary. If it fails, stop and report.
2. **Read** context.json with the Read tool:
   - `groups`: each market's share of the portfolio, looking through funds, with its holdings.
   - `holdings`: every position with `weight`, `price_asof` (the NAV or price date the
     dashboard uses), `set_symbol` (Thai stocks) and `sec_ticker` (US stocks).
   - `markets`: overnight tiles and early-trade quotes. They are published as they are;
     don't retype them, but you may quote them in text.
   - `nav_lags`: funds priced days behind their market, with the market's move since.
   - `feed_items`: ranked headlines from the allowlisted feeds inside the news window.
   - `filings`: SEC filings from the US stocks held, since yesterday.
   - `calendar`, `radar`, `allowed_domains`, `window`, `feed_status`.
3. **Research** (about 10–15 searches, 10 minutes):
   - For each group above 3%, run WebSearch with `allowed_domains` set to
     context.allowed_domains. Typical topics: Korea (KOSPI, Samsung, SK hynix); United States
     (Fed, Treasury yields, S&P 500, results from the largest index companies); Thailand (SET,
     Bank of Thailand, baht, Thai stocks held); Healthcare (Eli Lilly, Novo Nordisk, drug
     pricing); Vietnam (VN-Index); Crypto (bitcoin); China (A-shares). Add any holding named
     in feed_items or filings, and any radar topic with feed hits.
   - Open (WebFetch) the items you will use. When an official source exists for a figure (a
     central-bank statement, an SEC exhibit 99.1, a company release), check the figure there.
   - Note failed feeds from `feed_status` for the report.
4. **Choose**, ranking by the share of the portfolio exposed times how material the event is:
   - `top3`: the three things that matter most to this portfolio today (fewer on a quiet day).
   - `stories`: up to 6. Put follow-ups in a story's `related` list rather than repeating them.
   - `briefly`: up to 4 short items: smaller impact, small holdings, or single-source news.
   - `also`: up to 3 short phrases (under 90 characters) for the end of the 60-second brief.
   - `radar`: only radar.json topics that have news inside the window.
   - `new_events`: upcoming dated events you verified (results dates, central-bank meetings,
     dividends), each with a source. They are kept in calendar.json for later editions.
   - When a fund above 2% is priced days behind its market (`nav_lags`), say how far the market
     has moved since, so the reader knows what is not in their numbers yet. Say it as of this
     morning ("this morning your dashboard prices SCBKEQTG at its 26 Oct NAV"): the dashboard
     refreshes again at 11:30, when newer fund NAVs usually arrive.
   - Holdings under 0.5% appear only for major events: results, deals, regulatory action.
5. **Write** the draft with the Write tool (schema below; pipeline/news/example_draft.json is
   a full example).
6. **Check.** Run the check command. Fix every ERROR and run it again until it prints OK.
7. **Publish.** Run the publish command. It writes docs/brief.json and the archive copy,
   commits "Morning brief — <date>" and pushes to GitHub Pages.
8. **Report** in 4–6 lines, starting "Morning brief <date>: published" (or "NOT published —
   <reason>"): the top three, the counts (stories, short items, sources, items checked
   against primary documents), failed feeds, anything you could not verify, and the site link.

If the network is down or the research finds nothing usable, don't publish an empty or
invented brief. Report what happened; the site keeps showing the last edition with a
"today's brief isn't in yet" note.

## Draft schema

    {
      "edition_date": "YYYY-MM-DD",                       // must match context.json
      "top3": [{"lead": "≤95 chars, bold sentence.", "text": "≤280 chars.",
                "holdings": ["SCBKEQTG"], "group": "Korea", "dir": "pos|neg|watch|neutral"}],
      "also": ["≤90 chars", "..."],
      "stories": [{
        "id": "lowercase-hyphen-id", "group": "Korea", "holdings": ["SCBKEQTG", "EWY"],
        "headline": "≤115 chars, your words", "when": "Wed 28 Oct · 14:00 ET",
        "what": "≤620 chars: what happened, with numbers",
        "why": "≤460 chars: why it matters to these holdings (labelled AI analysis on the page)",
        "dir": "pos|neg|watch|neutral", "impact": 1,             // 3 high, 2 medium, 1 low
        "verify": "primary|multi|single|differ", "verify_note": "Checked against the FOMC statement",
        "sources": [{"name": "Federal Reserve", "url": "https://...", "primary": true}],
        "related": [{"label": "Also this morning", "headline": "...", "text": "≤360 chars",
                     "sources": [{"name": "...", "url": "https://..."}]}],
        "search": "≤60 chars for the Find on Reuters / FT links"
      }],
      "briefly": [{"headline": "...", "text": "≤320 chars", "holdings": [], "group": "Vietnam",
                   "verify": "single", "verify_note": "Single source", "sources": [...]}],
      "radar": [{"topic": "Anthropic IPO", "text": "≤380 chars", "sources": [...]}],
      "new_events": [{"date": "YYYY-MM-DD", "time_bkt": "HH:MM", "title": "≤90 chars",
                      "detail": "≤80 chars", "holdings": ["AAPL"], "kind": "earnings",
                      "source": {"name": "Apple IR", "url": "https://..."}}]
    }

- `holdings` use names exactly as in context.holdings; give holdings or a group, or both.
  The page computes "touches X% of your portfolio" from them: named holdings when given,
  otherwise the whole group.
- `verify`: `primary` needs a source marked primary; `multi` and `differ` need two or more
  different outlets; `single` means one outlet.
- Exposure figures, tiers, paywall marks, Reuters/FT search links and SET links are added
  by the publisher; don't write them.

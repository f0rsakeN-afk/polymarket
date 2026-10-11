# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: markets-live.spec.ts >> markets grid is live >> a published price reaches the card without a reload
- Location: e2e/markets-live.spec.ts:61:3

# Error details

```
Error: expect(received).toBe(expected) // Object.is equality

Expected: 77
Received: 62

Call Log:
- Timeout 10000ms exceeded while waiting on the predicate
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - button "Open Tanstack query devtools" [ref=e52] [cursor=pointer]
  - link "Skip to main content" [ref=e101] [cursor=pointer]:
    - /url: "#main-content"
  - generic [ref=e102]:
    - banner [ref=e103]:
      - generic [ref=e104]:
        - generic [ref=e105]:
          - link "PredictX home" [ref=e106] [cursor=pointer]:
            - /url: /
            - img "predictx logo" [ref=e107]
            - generic [ref=e108]: PredictX
          - navigation "Primary" [ref=e109]:
            - link "Markets" [ref=e110] [cursor=pointer]:
              - /url: /markets
            - link "Trades" [ref=e111] [cursor=pointer]:
              - /url: /trades
        - generic [ref=e112]:
          - search [ref=e114]:
            - generic [ref=e115]: Search markets
            - textbox "Search markets" [ref=e116]:
              - /placeholder: Search markets...
          - generic [ref=e117]:
            - heading "Command Palette" [level=2] [ref=e118]
            - paragraph [ref=e119]: Search for a command to run...
          - button "Toggle theme" [ref=e120] [cursor=pointer]
          - button "Sign in" [ref=e127] [cursor=pointer]
    - main [ref=e128]:
      - generic [ref=e129]:
        - generic [ref=e130]:
          - heading "Markets" [level=1] [ref=e131]
          - paragraph [ref=e132]: Browse and trade on prediction markets
        - textbox "Search markets" [ref=e134]:
          - /placeholder: Search markets...
        - generic [ref=e135]:
          - button "All" [ref=e136] [cursor=pointer]
          - button "Crypto" [ref=e137] [cursor=pointer]
          - button "Politics" [ref=e138] [cursor=pointer]
          - button "Finance" [ref=e139] [cursor=pointer]
          - button "Science" [ref=e140] [cursor=pointer]
          - button "Sports" [ref=e141] [cursor=pointer]
          - button "Other" [ref=e142] [cursor=pointer]
        - generic [ref=e143]:
          - list "Markets" [ref=e144]:
            - listitem [ref=e145]:
              - article [ref=e146]:
                - link "View Will Bitcoin exceed $100,000 in 2024?" [ref=e148] [cursor=pointer]:
                  - /url: /markets/bitcoin-100k-2024
                  - heading "Will Bitcoin exceed $100,000 in 2024?" [level=3] [ref=e149]
                - generic [ref=e151]:
                  - generic [ref=e152]:
                    - paragraph [ref=e154]: "Yes"
                    - generic [ref=e155]:
                      - generic [ref=e156]: 62%
                      - link "Trade Yes" [ref=e157] [cursor=pointer]:
                        - /url: /markets/bitcoin-100k-2024?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e158] [cursor=pointer]:
                        - /url: /markets/bitcoin-100k-2024?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e159]:
                    - paragraph [ref=e161]: "No"
                    - generic [ref=e162]:
                      - generic [ref=e163]: 38%
                      - link "Trade Yes" [ref=e164] [cursor=pointer]:
                        - /url: /markets/bitcoin-100k-2024?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e165] [cursor=pointer]:
                        - /url: /markets/bitcoin-100k-2024?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e166]:
                  - generic [ref=e167]:
                    - generic "Live — streaming prices" [ref=e168]
                    - generic [ref=e171]: $5.6M Vol
                  - generic [ref=e172]: Apr 6
            - listitem [ref=e173]:
              - article [ref=e174]:
                - link "View Will US enter recession in 2024?" [ref=e176] [cursor=pointer]:
                  - /url: /markets/us-recession-2024
                  - heading "Will US enter recession in 2024?" [level=3] [ref=e177]
                - generic [ref=e179]:
                  - generic [ref=e180]:
                    - paragraph [ref=e182]: "Yes"
                    - generic [ref=e183]:
                      - generic [ref=e184]: 35%
                      - link "Trade Yes" [ref=e185] [cursor=pointer]:
                        - /url: /markets/us-recession-2024?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e186] [cursor=pointer]:
                        - /url: /markets/us-recession-2024?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e187]:
                    - paragraph [ref=e189]: "No"
                    - generic [ref=e190]:
                      - generic [ref=e191]: 65%
                      - link "Trade Yes" [ref=e192] [cursor=pointer]:
                        - /url: /markets/us-recession-2024?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e193] [cursor=pointer]:
                        - /url: /markets/us-recession-2024?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e194]:
                  - generic [ref=e195]:
                    - generic "Live — streaming prices" [ref=e196]
                    - generic [ref=e199]: $5.1M Vol
                  - generic [ref=e200]: Aug 4
            - listitem [ref=e201]:
              - article [ref=e202]:
                - link "View Will Fed cut rates 3+ times in 2024?" [ref=e204] [cursor=pointer]:
                  - /url: /markets/fed-rate-cut-3
                  - heading "Will Fed cut rates 3+ times in 2024?" [level=3] [ref=e205]
                - generic [ref=e207]:
                  - generic [ref=e208]:
                    - paragraph [ref=e210]: "Yes"
                    - generic [ref=e211]:
                      - generic [ref=e212]: 48%
                      - link "Trade Yes" [ref=e213] [cursor=pointer]:
                        - /url: /markets/fed-rate-cut-3?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e214] [cursor=pointer]:
                        - /url: /markets/fed-rate-cut-3?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e215]:
                    - paragraph [ref=e217]: "No"
                    - generic [ref=e218]:
                      - generic [ref=e219]: 52%
                      - link "Trade Yes" [ref=e220] [cursor=pointer]:
                        - /url: /markets/fed-rate-cut-3?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e221] [cursor=pointer]:
                        - /url: /markets/fed-rate-cut-3?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e222]:
                  - generic [ref=e223]:
                    - generic "Live — streaming prices" [ref=e224]
                    - generic [ref=e227]: $4.2M Vol
                  - generic [ref=e228]: Jul 5
            - listitem [ref=e229]:
              - article [ref=e230]:
                - generic [ref=e231]:
                  - generic "8 outcomes" [ref=e232]: 8 options
                  - link "View Which country will win Euro 2024?" [ref=e233] [cursor=pointer]:
                    - /url: /markets/euro-2024-winner
                    - heading "Which country will win Euro 2024?" [level=3] [ref=e234]
                - generic [ref=e237]:
                  - link "France 49%" [ref=e238] [cursor=pointer]:
                    - /url: /markets/euro-2024-winner?outcomeIndex=0
                    - generic [ref=e239]:
                      - generic [ref=e240]: France
                      - generic [ref=e241]: 49%
                  - link "England 19%" [ref=e244] [cursor=pointer]:
                    - /url: /markets/euro-2024-winner?outcomeIndex=1
                    - generic [ref=e245]:
                      - generic [ref=e246]: England
                      - generic [ref=e247]: 19%
                  - link "Germany 10%" [ref=e250] [cursor=pointer]:
                    - /url: /markets/euro-2024-winner?outcomeIndex=2
                    - generic [ref=e251]:
                      - generic [ref=e252]: Germany
                      - generic [ref=e253]: 10%
                  - link "+5 more" [ref=e256] [cursor=pointer]:
                    - /url: /markets/euro-2024-winner
                - generic [ref=e257]:
                  - generic [ref=e258]:
                    - generic "Live — streaming prices" [ref=e259]
                    - generic [ref=e262]: $3.5M Vol
                  - generic [ref=e263]: Nov 7
            - listitem [ref=e264]:
              - article [ref=e265]:
                - link "View Will S&P 500 exceed 5,000 by end of 2024?" [ref=e267] [cursor=pointer]:
                  - /url: /markets/sp500-5000
                  - heading "Will S&P 500 exceed 5,000 by end of 2024?" [level=3] [ref=e268]
                - generic [ref=e270]:
                  - generic [ref=e271]:
                    - paragraph [ref=e273]: "Yes"
                    - generic [ref=e274]:
                      - generic [ref=e275]: 68%
                      - link "Trade Yes" [ref=e276] [cursor=pointer]:
                        - /url: /markets/sp500-5000?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e277] [cursor=pointer]:
                        - /url: /markets/sp500-5000?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e278]:
                    - paragraph [ref=e280]: "No"
                    - generic [ref=e281]:
                      - generic [ref=e282]: 32%
                      - link "Trade Yes" [ref=e283] [cursor=pointer]:
                        - /url: /markets/sp500-5000?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e284] [cursor=pointer]:
                        - /url: /markets/sp500-5000?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e285]:
                  - generic [ref=e286]:
                    - generic "Live — streaming prices" [ref=e287]
                    - generic [ref=e290]: $3.5M Vol
                  - generic [ref=e291]: Jul 5
            - listitem [ref=e292]:
              - article [ref=e293]:
                - link "View Will OpenAI achieve AGI by end of 2025?" [ref=e295] [cursor=pointer]:
                  - /url: /markets/openai-agi-2025
                  - heading "Will OpenAI achieve AGI by end of 2025?" [level=3] [ref=e296]
                - generic [ref=e298]:
                  - generic [ref=e299]:
                    - paragraph [ref=e301]: "Yes"
                    - generic [ref=e302]:
                      - generic [ref=e303]: 25%
                      - link "Trade Yes" [ref=e304] [cursor=pointer]:
                        - /url: /markets/openai-agi-2025?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e305] [cursor=pointer]:
                        - /url: /markets/openai-agi-2025?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e306]:
                    - paragraph [ref=e308]: "No"
                    - generic [ref=e309]:
                      - generic [ref=e310]: 75%
                      - link "Trade Yes" [ref=e311] [cursor=pointer]:
                        - /url: /markets/openai-agi-2025?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e312] [cursor=pointer]:
                        - /url: /markets/openai-agi-2025?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e313]:
                  - generic [ref=e314]:
                    - generic "Live — streaming prices" [ref=e315]
                    - generic [ref=e318]: $3.2M Vol
                  - generic [ref=e319]: Mar 31
            - listitem [ref=e320]:
              - article [ref=e321]:
                - link "View Will SpaceX land humans on Mars by 2026?" [ref=e323] [cursor=pointer]:
                  - /url: /markets/spacex-mars-2026
                  - heading "Will SpaceX land humans on Mars by 2026?" [level=3] [ref=e324]
                - generic [ref=e326]:
                  - generic [ref=e327]:
                    - paragraph [ref=e329]: "Yes"
                    - generic [ref=e330]:
                      - generic [ref=e331]: 15%
                      - link "Trade Yes" [ref=e332] [cursor=pointer]:
                        - /url: /markets/spacex-mars-2026?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e333] [cursor=pointer]:
                        - /url: /markets/spacex-mars-2026?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e334]:
                    - paragraph [ref=e336]: "No"
                    - generic [ref=e337]:
                      - generic [ref=e338]: 85%
                      - link "Trade Yes" [ref=e339] [cursor=pointer]:
                        - /url: /markets/spacex-mars-2026?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e340] [cursor=pointer]:
                        - /url: /markets/spacex-mars-2026?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e341]:
                  - generic [ref=e342]:
                    - generic "Live — streaming prices" [ref=e343]
                    - generic [ref=e346]: $2.8M Vol
                  - generic [ref=e347]: Mar 26
            - listitem [ref=e348]:
              - article [ref=e349]:
                - generic [ref=e350]:
                  - generic [ref=e351]: Resolved
                  - link "View Will GTA 6 be released in 2024?" [ref=e352] [cursor=pointer]:
                    - /url: /markets/gta6-2024
                    - heading "Will GTA 6 be released in 2024?" [level=3] [ref=e353]
                - generic [ref=e356]:
                  - generic [ref=e357]: Final result
                  - generic [ref=e358]: Outcome not recorded for this market
                  - generic [ref=e359]: Settled • no longer tradeable
                - generic [ref=e360]:
                  - generic [ref=e361]:
                    - generic "Live — streaming prices" [ref=e362]
                    - generic [ref=e365]: $2.8M Vol
                  - generic [ref=e366]: Sep 8
            - listitem [ref=e367]:
              - article [ref=e368]:
                - generic [ref=e369]:
                  - generic [ref=e370]: Resolved
                  - link "View Will Donald Trump win the 2024 US Presidential Election?" [ref=e371] [cursor=pointer]:
                    - /url: /markets/trump-2024-wins
                    - heading "Will Donald Trump win the 2024 US Presidential Election?" [level=3] [ref=e372]
                - generic [ref=e375]:
                  - generic [ref=e376]: Final result
                  - generic [ref=e377]: Outcome not recorded for this market
                  - generic [ref=e378]: Settled • no longer tradeable
                - generic [ref=e379]:
                  - generic [ref=e380]:
                    - generic "Live — streaming prices" [ref=e381]
                    - generic [ref=e384]: $2.5M Vol
                  - generic [ref=e385]: Sep 26
            - listitem [ref=e386]:
              - article [ref=e387]:
                - generic [ref=e388]:
                  - generic [ref=e389]: Resolved
                  - link "View Will Ethereum ETF be approved by SEC in 2024?" [ref=e390] [cursor=pointer]:
                    - /url: /markets/ethereum-etf-2024
                    - heading "Will Ethereum ETF be approved by SEC in 2024?" [level=3] [ref=e391]
                - generic [ref=e394]:
                  - generic [ref=e395]: Final result
                  - generic [ref=e396]: Outcome not recorded for this market
                  - generic [ref=e397]: Settled • no longer tradeable
                - generic [ref=e398]:
                  - generic [ref=e399]:
                    - generic "Live — streaming prices" [ref=e400]
                    - generic [ref=e403]: $2.1M Vol
                  - generic [ref=e404]: Sep 27
            - listitem [ref=e405]:
              - article [ref=e406]:
                - generic [ref=e407]:
                  - generic "6 outcomes" [ref=e408]: 6 options
                  - link "View Which team will win the 2025 NBA Championship?" [ref=e409] [cursor=pointer]:
                    - /url: /markets/nba-championship-2025
                    - heading "Which team will win the 2025 NBA Championship?" [level=3] [ref=e410]
                - generic [ref=e413]:
                  - link "Boston Celtics 52%" [ref=e414] [cursor=pointer]:
                    - /url: /markets/nba-championship-2025?outcomeIndex=0
                    - generic [ref=e415]:
                      - generic [ref=e416]: Boston Celtics
                      - generic [ref=e417]: 52%
                  - link "Los Angeles Lakers 20%" [ref=e420] [cursor=pointer]:
                    - /url: /markets/nba-championship-2025?outcomeIndex=1
                    - generic [ref=e421]:
                      - generic [ref=e422]: Los Angeles Lakers
                      - generic [ref=e423]: 20%
                  - link "Denver Nuggets 11%" [ref=e426] [cursor=pointer]:
                    - /url: /markets/nba-championship-2025?outcomeIndex=2
                    - generic [ref=e427]:
                      - generic [ref=e428]: Denver Nuggets
                      - generic [ref=e429]: 11%
                  - link "+3 more" [ref=e432] [cursor=pointer]:
                    - /url: /markets/nba-championship-2025
                - generic [ref=e433]:
                  - generic [ref=e434]:
                    - generic "Live — streaming prices" [ref=e435]
                    - generic [ref=e438]: $2.1M Vol
                  - generic [ref=e439]: Nov 12
            - listitem [ref=e440]:
              - article [ref=e441]:
                - link "View Will Labour win a majority in the 2024 UK General Election?" [ref=e443] [cursor=pointer]:
                  - /url: /markets/uk-labour-majority
                  - heading "Will Labour win a majority in the 2024 UK General Election?" [level=3] [ref=e444]
                - generic [ref=e446]:
                  - generic [ref=e447]:
                    - paragraph [ref=e449]: "Yes"
                    - generic [ref=e450]:
                      - generic [ref=e451]: 72%
                      - link "Trade Yes" [ref=e452] [cursor=pointer]:
                        - /url: /markets/uk-labour-majority?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e453] [cursor=pointer]:
                        - /url: /markets/uk-labour-majority?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e454]:
                    - paragraph [ref=e456]: "No"
                    - generic [ref=e457]:
                      - generic [ref=e458]: 28%
                      - link "Trade Yes" [ref=e459] [cursor=pointer]:
                        - /url: /markets/uk-labour-majority?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e460] [cursor=pointer]:
                        - /url: /markets/uk-labour-majority?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e461]:
                  - generic [ref=e462]:
                    - generic "Live — streaming prices" [ref=e463]
                    - generic [ref=e466]: $1.2M Vol
                  - generic [ref=e467]: Jan 6
            - listitem [ref=e468]:
              - article [ref=e469]:
                - generic [ref=e470]:
                  - generic [ref=e471]: Resolved
                  - link "View Will USA top medal table at Paris 2024?" [ref=e472] [cursor=pointer]:
                    - /url: /markets/olympics-2024-usa-top
                    - heading "Will USA top medal table at Paris 2024?" [level=3] [ref=e473]
                - generic [ref=e476]:
                  - generic [ref=e477]: Final result
                  - generic [ref=e478]: Outcome not recorded for this market
                  - generic [ref=e479]: Settled • no longer tradeable
                - generic [ref=e480]:
                  - generic [ref=e481]:
                    - generic "Live — streaming prices" [ref=e482]
                    - generic [ref=e485]: $1.1M Vol
                  - generic [ref=e486]: Sep 25
            - listitem [ref=e487]:
              - article [ref=e488]:
                - generic [ref=e489]:
                  - generic [ref=e490]: Resolved
                  - link "View Will Taylor Swift's Eras Tour exceed $2B revenue?" [ref=e491] [cursor=pointer]:
                    - /url: /markets/swift-tour-2b
                    - heading "Will Taylor Swift's Eras Tour exceed $2B revenue?" [level=3] [ref=e492]
                - generic [ref=e495]:
                  - generic [ref=e496]: Final result
                  - generic [ref=e497]: Outcome not recorded for this market
                  - generic [ref=e498]: Settled • no longer tradeable
                - generic [ref=e499]:
                  - generic [ref=e500]:
                    - generic "Live — streaming prices" [ref=e501]
                    - generic [ref=e504]: $920.0K Vol
                  - generic [ref=e505]: Sep 23
            - listitem [ref=e506]:
              - article [ref=e507]:
                - link "View Will Biden's approval rating exceed 45% in Q4 2024?" [ref=e509] [cursor=pointer]:
                  - /url: /markets/biden-approval-45
                  - heading "Will Biden's approval rating exceed 45% in Q4 2024?" [level=3] [ref=e510]
                - generic [ref=e512]:
                  - generic [ref=e513]:
                    - paragraph [ref=e515]: "Yes"
                    - generic [ref=e516]:
                      - generic [ref=e517]: 38%
                      - link "Trade Yes" [ref=e518] [cursor=pointer]:
                        - /url: /markets/biden-approval-45?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e519] [cursor=pointer]:
                        - /url: /markets/biden-approval-45?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e520]:
                    - paragraph [ref=e522]: "No"
                    - generic [ref=e523]:
                      - generic [ref=e524]: 62%
                      - link "Trade Yes" [ref=e525] [cursor=pointer]:
                        - /url: /markets/biden-approval-45?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e526] [cursor=pointer]:
                        - /url: /markets/biden-approval-45?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e527]:
                  - generic [ref=e528]:
                    - generic "Live — streaming prices" [ref=e529]
                    - generic [ref=e532]: $850.5K Vol
                  - generic [ref=e533]: Dec 7
            - listitem [ref=e534]:
              - article [ref=e535]:
                - link "View Will 2024 be the hottest year on record?" [ref=e537] [cursor=pointer]:
                  - /url: /markets/climate-2024-hottest
                  - heading "Will 2024 be the hottest year on record?" [level=3] [ref=e538]
                - generic [ref=e540]:
                  - generic [ref=e541]:
                    - paragraph [ref=e543]: "Yes"
                    - generic [ref=e544]:
                      - generic [ref=e545]: 82%
                      - link "Trade Yes" [ref=e546] [cursor=pointer]:
                        - /url: /markets/climate-2024-hottest?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e547] [cursor=pointer]:
                        - /url: /markets/climate-2024-hottest?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e548]:
                    - paragraph [ref=e550]: "No"
                    - generic [ref=e551]:
                      - generic [ref=e552]: 18%
                      - link "Trade Yes" [ref=e553] [cursor=pointer]:
                        - /url: /markets/climate-2024-hottest?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e554] [cursor=pointer]:
                        - /url: /markets/climate-2024-hottest?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e555]:
                  - generic [ref=e556]:
                    - generic "Live — streaming prices" [ref=e557]
                    - generic [ref=e560]: $680.0K Vol
                  - generic [ref=e561]: Jul 5
            - listitem [ref=e562]:
              - article [ref=e563]:
                - link "View Will Apple Vision Pro sales exceed 500K units in 2024?" [ref=e565] [cursor=pointer]:
                  - /url: /markets/apple-vision-pro-500k
                  - heading "Will Apple Vision Pro sales exceed 500K units in 2024?" [level=3] [ref=e566]
                - generic [ref=e568]:
                  - generic [ref=e569]:
                    - paragraph [ref=e571]: "Yes"
                    - generic [ref=e572]:
                      - generic [ref=e573]: 45%
                      - link "Trade Yes" [ref=e574] [cursor=pointer]:
                        - /url: /markets/apple-vision-pro-500k?outcomeIndex=0&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e575] [cursor=pointer]:
                        - /url: /markets/apple-vision-pro-500k?outcomeIndex=0&side=no
                        - text: "No"
                  - generic [ref=e576]:
                    - paragraph [ref=e578]: "No"
                    - generic [ref=e579]:
                      - generic [ref=e580]: 55%
                      - link "Trade Yes" [ref=e581] [cursor=pointer]:
                        - /url: /markets/apple-vision-pro-500k?outcomeIndex=1&side=buy
                        - text: "Yes"
                      - link "Trade No" [ref=e582] [cursor=pointer]:
                        - /url: /markets/apple-vision-pro-500k?outcomeIndex=1&side=no
                        - text: "No"
                - generic [ref=e583]:
                  - generic [ref=e584]:
                    - generic "Live — streaming prices" [ref=e585]
                    - generic [ref=e588]: $680.0K Vol
                  - generic [ref=e589]: Apr 6
          - generic [ref=e590]: No more markets
    - contentinfo [ref=e592]:
      - generic [ref=e593]:
        - generic [ref=e594]:
          - generic [ref=e595]:
            - heading "Stay in the loop" [level=2] [ref=e596]
            - paragraph [ref=e597]: Get the latest market insights, product updates, and platform announcements delivered to your inbox.
          - form "Newsletter signup" [ref=e598]:
            - generic [ref=e599]: Email address
            - textbox "Email address" [ref=e600]:
              - /placeholder: your@email.com
            - button "Subscribe" [ref=e601] [cursor=pointer]
        - generic [ref=e602]:
          - generic [ref=e603]:
            - link "predictx logo PredictX" [ref=e604] [cursor=pointer]:
              - /url: /
              - img "predictx logo" [ref=e605]
              - generic [ref=e606]: PredictX
            - paragraph [ref=e607]: A decentralized prediction market platform for trading on the outcome of real-world events.
            - generic [ref=e608]:
              - link "X (Twitter)" [ref=e609] [cursor=pointer]:
                - /url: https://x.com
              - link "Discord" [ref=e612] [cursor=pointer]:
                - /url: https://discord.com
              - link "Telegram" [ref=e615] [cursor=pointer]:
                - /url: https://t.me
          - generic [ref=e618]:
            - heading "Platform" [level=2] [ref=e619]
            - list [ref=e620]:
              - listitem [ref=e621]:
                - link "Markets" [ref=e622] [cursor=pointer]:
                  - /url: /markets
              - listitem [ref=e623]:
                - link "Trade Feed" [ref=e624] [cursor=pointer]:
                  - /url: /trades
              - listitem [ref=e625]:
                - link "Orders" [ref=e626] [cursor=pointer]:
                  - /url: /orders
              - listitem [ref=e627]:
                - link "Portfolio" [ref=e628] [cursor=pointer]:
                  - /url: /portfolio
              - listitem [ref=e629]:
                - link "Wallet" [ref=e630] [cursor=pointer]:
                  - /url: /wallet
          - generic [ref=e631]:
            - heading "Resources" [level=2] [ref=e632]
            - list [ref=e633]:
              - listitem [ref=e634]:
                - link "FAQ" [ref=e635] [cursor=pointer]:
                  - /url: /faq
              - listitem [ref=e636]:
                - link "Documentation" [ref=e637] [cursor=pointer]:
                  - /url: /docs
              - listitem [ref=e638]:
                - link "API Reference" [ref=e639] [cursor=pointer]:
                  - /url: /api
              - listitem [ref=e640]:
                - link "Support" [ref=e641] [cursor=pointer]:
                  - /url: /support
          - generic [ref=e642]:
            - heading "Legal" [level=2] [ref=e643]
            - list [ref=e644]:
              - listitem [ref=e645]:
                - link "Terms of Service" [ref=e646] [cursor=pointer]:
                  - /url: /legal/terms
              - listitem [ref=e647]:
                - link "Privacy Policy" [ref=e648] [cursor=pointer]:
                  - /url: /legal/privacy
              - listitem [ref=e649]:
                - link "Risk Disclosure" [ref=e650] [cursor=pointer]:
                  - /url: /legal/risk
        - generic [ref=e651]:
          - paragraph [ref=e652]: © 2026 PredictX. All rights reserved.
          - generic [ref=e653]:
            - link "Privacy" [ref=e654] [cursor=pointer]:
              - /url: /legal/privacy
            - generic [aria-hidden] [ref=e655]: ·
            - link "Terms" [ref=e656] [cursor=pointer]:
              - /url: /legal/terms
            - generic [aria-hidden] [ref=e657]: ·
            - link "Risks" [ref=e658] [cursor=pointer]:
              - /url: /legal/risk
  - button "Open Next.js Dev Tools" [ref=e664] [cursor=pointer]
  - alert [ref=e668]
```

# Test source

```ts
  1   | import { test, expect } from "@playwright/test"
  2   | import { execSync } from "node:child_process"
  3   | 
  4   | /**
  5   |  * The one property the entire system exists for.
  6   |  *
  7   |  * Every other test in this repo can pass while the markets page renders a
  8   |  * perfectly composed grid of prices that never move. Nothing here proves the
  9   |  * browser is *connected to anything*, because nothing here asks.
  10  |  *
  11  |  * So this asks directly: publish a price the way the order service does, and
  12  |  * require the number on screen to follow. A live badge, a connected socket, or a
  13  |  * green status light are all consistent with a page that renders beautifully and
  14  |  * never changes - this is the only assertion that is not.
  15  |  */
  16  | 
  17  | const MARKET_ID = process.env.E2E_MARKET_ID
  18  | const BACKEND = process.env.E2E_BACKEND_DIR ?? "../../../backend"
  19  | 
  20  | /** Publish one price frame through the production path (Lua sequencer + Redis). */
  21  | function publishPrice(yesPrice: number): boolean {
  22  |   try {
  23  |     execSync(
  24  |       `cd ${BACKEND} && REDIS_PASSWORD=${process.env.REDIS_PASSWORD ?? "devpass"} ` +
  25  |         `.venv/bin/python -m harness.push_price ${MARKET_ID} ${yesPrice}`,
  26  |       { shell: "/bin/bash", stdio: "pipe", env: process.env },
  27  |     )
  28  |     return true
  29  |   } catch {
  30  |     return false
  31  |   }
  32  | }
  33  | 
  34  | /** The first two percentages on the first card, as Yes / No. */
  35  | async function firstCardPrices(page: import("@playwright/test").Page) {
  36  |   return page.evaluate(() => {
  37  |     const cell = document.querySelector("[data-index]")
  38  |     if (!cell) return null
  39  |     return [...cell.querySelectorAll("span")]
  40  |       .map((s) => s.textContent?.trim() ?? "")
  41  |       .filter((t) => /^\d+%$/.test(t))
  42  |       .slice(0, 2)
  43  |       .map((t) => Number(t.replace("%", "")))
  44  |   })
  45  | }
  46  | 
  47  | /**
  48  |  * Skip rather than fail when the harness cannot run.
  49  |  *
  50  |  * These need a live backend, a live Redis, and a seeded market. In an isolated
  51  |  * checkout none of that exists, and a red suite nobody can fix locally gets
  52  |  * ignored - which is worse than an honest skip that says what is missing.
  53  |  */
  54  | test.describe("markets grid is live", () => {
  55  |   test.skip(!MARKET_ID, "E2E_MARKET_ID not set - needs a seeded market to move")
  56  |   test.skip(
  57  |     !process.env.REDIS_PASSWORD,
  58  |     "REDIS_PASSWORD not set - the publisher needs the same Redis the app uses",
  59  |   )
  60  | 
  61  |   test("a published price reaches the card without a reload", async ({ page }) => {
  62  |     await page.goto("/markets")
  63  |     await page.waitForSelector("[data-index]", { timeout: 20_000 })
  64  |     await page.waitForTimeout(1500) // let the socket declare its grid
  65  | 
  66  |     const before = await firstCardPrices(page)
  67  |     expect(before, "the card rendered no prices to begin with").not.toBeNull()
  68  |     expect(before!.length).toBeGreaterThanOrEqual(2)
  69  | 
  70  |     // Something guaranteed to differ from the seeded price, and valid for both
  71  |     // sides so the card's Yes and No cannot both be impossible.
  72  |     const target = before![0] === 77 ? 31 : 77
  73  |     expect(publishPrice(target / 100), "could not publish to Redis").toBe(true)
  74  | 
  75  |     await expect
  76  |       .poll(async () => (await firstCardPrices(page))?.[0], { timeout: 10_000 })
> 77  |       .toBe(target)
      |        ^ Error: expect(received).toBe(expected) // Object.is equality
  78  | 
  79  |     // The complement must follow too. A grid that updated only the Yes side would
  80  |     // show a market priced at 77 and 38, which sums past 100.
  81  |     const after = await firstCardPrices(page)
  82  |     expect(after![0] + after![1]).toBe(100)
  83  |   })
  84  | 
  85  |   test("keeps many cards live at once, not just the first", async ({ page }) => {
  86  |     await page.goto("/markets")
  87  |     await page.waitForSelector("[data-index]", { timeout: 20_000 })
  88  |     await page.waitForTimeout(1500)
  89  | 
  90  |     const cells = await page.locator("[data-index]").count()
  91  |     expect(cells).toBeGreaterThan(2)
  92  | 
  93  |     // Only the first card's market is being published to, so this asserts the
  94  |     // *other* cards are left alone - a grid that repainted wholesale on every
  95  |     // frame would pass a naive "something changed" check while being wrong.
  96  |     const others = await page.evaluate(() =>
  97  |       [...document.querySelectorAll("[data-index]")]
  98  |         .slice(1, 4)
  99  |         .map((c) => c.textContent),
  100 |     )
  101 |     expect(publishPrice(0.63)).toBe(true)
  102 |     await page.waitForTimeout(1500)
  103 |     const after = await page.evaluate(() =>
  104 |       [...document.querySelectorAll("[data-index]")].slice(1, 4).map((c) => c.textContent),
  105 |     )
  106 |     expect(after).toEqual(others)
  107 |   })
  108 | })
```
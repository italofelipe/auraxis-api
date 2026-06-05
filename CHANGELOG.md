# Changelog

## [1.55.1](https://github.com/italofelipe/auraxis-api/compare/v1.55.0...v1.55.1) (2026-06-05)


### Bug Fixes

* **ci:** correct TruffleHog base ref on push to default branch ([d5422f9](https://github.com/italofelipe/auraxis-api/commit/d5422f9ee08975b377fa0d723b493d0f931c1c96))
* **graphql:** pin graphql-core + regen introspection bundle; fix TruffleHog base on push ([6f69351](https://github.com/italofelipe/auraxis-api/commit/6f693515a6c2da2bfe718edf1113902d75f2c31e))
* **graphql:** pin graphql-core==3.2.11 and regenerate introspection bundle ([8287b0f](https://github.com/italofelipe/auraxis-api/commit/8287b0f98dea9e7ac49aa994eeb3942c1736a1a1)), closes [#1450](https://github.com/italofelipe/auraxis-api/issues/1450)

## [1.55.0](https://github.com/italofelipe/auraxis-api/compare/v1.54.2...v1.55.0) (2026-06-04)


### Features

* **notifications:** web push (VAPID) send + alert dispatch ([#1446](https://github.com/italofelipe/auraxis-api/issues/1446)) ([224d55d](https://github.com/italofelipe/auraxis-api/commit/224d55dde1ba3d027202fda3f799f7034a5f5790))
* **notifications:** web push (VAPID) send + alert dispatch ([#1446](https://github.com/italofelipe/auraxis-api/issues/1446)) ([8a91873](https://github.com/italofelipe/auraxis-api/commit/8a91873497f1e112416ac0fb560efed9907acbea))
* **transactions:** delete recurring occurrence vs whole series ([#1444](https://github.com/italofelipe/auraxis-api/issues/1444)) ([f45d689](https://github.com/italofelipe/auraxis-api/commit/f45d6892559441e1cd2f725ba716aa6ca5bbd514))
* **transactions:** delete recurring occurrence vs whole series ([#1444](https://github.com/italofelipe/auraxis-api/issues/1444)) ([3061478](https://github.com/italofelipe/auraxis-api/commit/306147843e73ae29c17416b286229cade9b5eac2))


### Bug Fixes

* **wallet:** expose cost_basis/current_value/change_percent ([#1442](https://github.com/italofelipe/auraxis-api/issues/1442)) ([b6e664e](https://github.com/italofelipe/auraxis-api/commit/b6e664ef6e11cc461fd6321ddd6cc1e0337e5104))
* **wallet:** expose cost_basis/current_value/change_percent on entries ([b2fd770](https://github.com/italofelipe/auraxis-api/commit/b2fd77060d6dac16692bef2d2d4f254607963907)), closes [#1442](https://github.com/italofelipe/auraxis-api/issues/1442)

## [1.54.2](https://github.com/italofelipe/auraxis-api/compare/v1.54.1...v1.54.2) (2026-06-03)


### Bug Fixes

* **cors:** allow X-CSRF-TOKEN header so reload restores session ([295109e](https://github.com/italofelipe/auraxis-api/commit/295109eb54c540ca81494177606343fa8bbcd616)), closes [#1436](https://github.com/italofelipe/auraxis-api/issues/1436)
* **cors:** allow X-CSRF-TOKEN so reload restores session ([#1436](https://github.com/italofelipe/auraxis-api/issues/1436)) ([44bf3e1](https://github.com/italofelipe/auraxis-api/commit/44bf3e15cd20b0daefdf3d31da7f4522f2d25ed9))

## [1.54.1](https://github.com/italofelipe/auraxis-api/compare/v1.54.0...v1.54.1) (2026-06-03)


### Bug Fixes

* **ai:** make weekly-summary read-only; move email to scheduled batch ([c92da4e](https://github.com/italofelipe/auraxis-api/commit/c92da4ef56224bd51c55ec93b58b672ac579f97d)), closes [#1420](https://github.com/italofelipe/auraxis-api/issues/1420)
* **ai:** weekly-summary read-only; email só no batch agendado ([014dd60](https://github.com/italofelipe/auraxis-api/commit/014dd60b533d9d35cbceac37e6a8d42148afaee7))
* **deploy:** pin FLASK_APP=run.py for migration docker exec ([f2271bb](https://github.com/italofelipe/auraxis-api/commit/f2271bb650dbda5409ab7a6adb7adf7ced1cdca7)), closes [#1431](https://github.com/italofelipe/auraxis-api/issues/1431)
* **deploy:** pinar FLASK_APP=run.py no docker exec das migrations ([db82d34](https://github.com/italofelipe/auraxis-api/commit/db82d34b43d37f5ba735d27f839e4fcd9e7f6e95))
* **deploy:** reset para origin/&lt;branch&gt; (causa-raiz do exit 36) ([791f75b](https://github.com/italofelipe/auraxis-api/commit/791f75bd3c164fc99f715ae28ecd4c696594e67e))
* **deploy:** reset to origin/&lt;branch&gt;, not stale local branch (exit 36 root cause) ([3cd02a3](https://github.com/italofelipe/auraxis-api/commit/3cd02a3b4c34f176300014db9b8be56ee77cf426)), closes [#1434](https://github.com/italofelipe/auraxis-api/issues/1434)
* **deploy:** surface alembic error on exit 36; harden WEB_CID ([57ae41a](https://github.com/italofelipe/auraxis-api/commit/57ae41af2d639563e9e57762cb7572b000e9c781)), closes [#1429](https://github.com/italofelipe/auraxis-api/issues/1429)
* **deploy:** tornar erro do alembic visível no exit 36 + endurecer $WEB_CID ([3039e65](https://github.com/italofelipe/auraxis-api/commit/3039e65cd06398c4ecb1ff56e50370660583d315))
* **migrations:** cons1/cc1/cc2/fb1/sq1 idempotentes — destrava deploy prod ([061811d](https://github.com/italofelipe/auraxis-api/commit/061811d564efb4eba8406cb4fd6a9d19a261398d))
* **migrations:** make cons1/cc1/cc2/fb1/sq1 idempotent ([63655db](https://github.com/italofelipe/auraxis-api/commit/63655dbfd2dc3d9f487636011138280d79449fbd)), closes [#1427](https://github.com/italofelipe/auraxis-api/issues/1427)
* **migrations:** make rec1 recurrence-cadence idempotent ([4d8fdd6](https://github.com/italofelipe/auraxis-api/commit/4d8fdd67b7df352db8b6d4667dc1c0f45c59e66e)), closes [#1425](https://github.com/italofelipe/auraxis-api/issues/1425)
* **migrations:** rec1 idempotente — destrava deploy prod (exit 36) ([e50554c](https://github.com/italofelipe/auraxis-api/commit/e50554c2ca2677f76ba0672bc9a461ad55d47642))
* **recurrence:** add flask reconcile command + daily schedule ([29e679a](https://github.com/italofelipe/auraxis-api/commit/29e679a6aa4fcbbaca4649aced946c1f1a1261c9)), closes [#1422](https://github.com/italofelipe/auraxis-api/issues/1422)
* **recurrence:** comando flask reconcile + agendamento diário (recorrentes somem em meses futuros) ([44c69a9](https://github.com/italofelipe/auraxis-api/commit/44c69a9368e9ec813b0c43a14e5afe70f4e34e58))

## [1.54.0](https://github.com/italofelipe/auraxis-api/compare/v1.53.0...v1.54.0) (2026-06-02)


### Features

* **ai:** gateway proxy /ai/insights/spending-patterns → v2 (PROD-04, [#567](https://github.com/italofelipe/auraxis-api/issues/567)) ([#1418](https://github.com/italofelipe/auraxis-api/issues/1418)) ([82226ec](https://github.com/italofelipe/auraxis-api/commit/82226eca102f65fabe08f0ba316f7aa01c1caf25))

## [1.53.0](https://github.com/italofelipe/auraxis-api/compare/v1.52.0...v1.53.0) (2026-06-01)


### Features

* **simulation:** contador de quota freemium + REST + GraphQL ([#1409](https://github.com/italofelipe/auraxis-api/issues/1409)) ([#1410](https://github.com/italofelipe/auraxis-api/issues/1410)) ([e7c07dd](https://github.com/italofelipe/auraxis-api/commit/e7c07dd6e1bf379d89fbb01b56d260f863ca41d1))


### Bug Fixes

* **ai:** cobertura incompleta de dimensões não derruba geração de insight ([#1412](https://github.com/italofelipe/auraxis-api/issues/1412)) ([#1413](https://github.com/italofelipe/auraxis-api/issues/1413)) ([f37c7e0](https://github.com/italofelipe/auraxis-api/commit/f37c7e0521ceba06fa90a6a7a5e931132b4922c4))

## [1.52.0](https://github.com/italofelipe/auraxis-api/compare/v1.51.0...v1.52.0) (2026-05-31)


### Features

* **ai:** instrument insight runs, cost, rejections, truncation & purge ([#1314](https://github.com/italofelipe/auraxis-api/issues/1314)) ([#1406](https://github.com/italofelipe/auraxis-api/issues/1406)) ([1189029](https://github.com/italofelipe/auraxis-api/commit/11890299af6d936198cf68e34628d618e9b4f2f4))


### Bug Fixes

* **ai:** exec weekly/monthly insights in running web container ([#1249](https://github.com/italofelipe/auraxis-api/issues/1249)) ([#1403](https://github.com/italofelipe/auraxis-api/issues/1403)) ([0950a7c](https://github.com/italofelipe/auraxis-api/commit/0950a7ce0c0f3a7fabb870ddbb3def6585e2c480))
* **deploy:** pin alembic upgrade + drift gate to the recreated web container ([#1405](https://github.com/italofelipe/auraxis-api/issues/1405)) ([#1407](https://github.com/italofelipe/auraxis-api/issues/1407)) ([41a3592](https://github.com/italofelipe/auraxis-api/commit/41a35923e2d70da93a5431d3ea84b12c7523c2a3))

## [1.51.0](https://github.com/italofelipe/auraxis-api/compare/v1.50.0...v1.51.0) (2026-05-31)


### Features

* **ai:** expose forecast flag on generateAiInsight (GraphQL parity) ([#1399](https://github.com/italofelipe/auraxis-api/issues/1399)) ([3c9c2f2](https://github.com/italofelipe/auraxis-api/commit/3c9c2f21a43614ce26d0168652afc1f9dc43d2dc)), closes [#1393](https://github.com/italofelipe/auraxis-api/issues/1393)
* **ai:** return persisted insight id on generation (REST + GraphQL) ([#1402](https://github.com/italofelipe/auraxis-api/issues/1402)) ([c37e41d](https://github.com/italofelipe/auraxis-api/commit/c37e41d5237a5b88ba6ecf35fb1b6c9d801384ec)), closes [#1400](https://github.com/italofelipe/auraxis-api/issues/1400)

## [1.50.0](https://github.com/italofelipe/auraxis-api/compare/v1.49.0...v1.50.0) (2026-05-31)


### Features

* **ai:** assertive transactions narrative + deterministic projections ([#1394](https://github.com/italofelipe/auraxis-api/issues/1394)) ([#1396](https://github.com/italofelipe/auraxis-api/issues/1396)) ([43c6456](https://github.com/italofelipe/auraxis-api/commit/43c6456ad6a6bf9eb6c4d26488a28c83fae4d14f))
* **ai:** automatic end-of-month recap batch + cron ([#1386](https://github.com/italofelipe/auraxis-api/issues/1386) slice B) ([#1397](https://github.com/italofelipe/auraxis-api/issues/1397)) ([b49f060](https://github.com/italofelipe/auraxis-api/commit/b49f0603eef3ee619f35b7e11fcbf64202ad66ff))
* **ai:** cost ceiling + 1/day & 30/month caps + strong model + admin bypass ([#1386](https://github.com/italofelipe/auraxis-api/issues/1386) slice A) ([#1390](https://github.com/italofelipe/auraxis-api/issues/1390)) ([3f7a9a7](https://github.com/italofelipe/auraxis-api/commit/3f7a9a70e9094249f6ad198dd6b6b711850aabc9))
* **ai:** forecast mode for future-month financial insights ([#1389](https://github.com/italofelipe/auraxis-api/issues/1389)) ([b3eef6a](https://github.com/italofelipe/auraxis-api/commit/b3eef6a9938f9b77619ddba4caafcfc76c345559))
* **ai:** insight feedback/rating loop — model + REST + GraphQL ([#1387](https://github.com/italofelipe/auraxis-api/issues/1387)) ([#1398](https://github.com/italofelipe/auraxis-api/issues/1398)) ([f63c339](https://github.com/italofelipe/auraxis-api/commit/f63c339bbba54928d4e6ac8012d9f5ad634849b7))

## [1.49.0](https://github.com/italofelipe/auraxis-api/compare/v1.48.0...v1.49.0) (2026-05-30)


### Features

* **infra:** add db service to docker-compose.prod.yml (Postgres 16, low-mem) ([#1380](https://github.com/italofelipe/auraxis-api/issues/1380)) ([4ba02ea](https://github.com/italofelipe/auraxis-api/commit/4ba02ea52931f28c679ce6aff0274a89477a4805)), closes [#1376](https://github.com/italofelipe/auraxis-api/issues/1376) [#1377](https://github.com/italofelipe/auraxis-api/issues/1377)
* **infra:** add migration script pg_dump RDS → restore local container ([#1381](https://github.com/italofelipe/auraxis-api/issues/1381)) ([77e6369](https://github.com/italofelipe/auraxis-api/commit/77e6369ebb2651540b077dcd77eb82a50c3e9ed3)), closes [#1378](https://github.com/italofelipe/auraxis-api/issues/1378)
* **transactions:** configurable recurrence cadence + materialize future months ([#1388](https://github.com/italofelipe/auraxis-api/issues/1388)) ([fc9b686](https://github.com/italofelipe/auraxis-api/commit/fc9b68649dff86fa8a08a9f9866a413c57a685a3))


### Bug Fixes

* repair refresh csrf and daily insight context ([#1364](https://github.com/italofelipe/auraxis-api/issues/1364)) ([d943318](https://github.com/italofelipe/auraxis-api/commit/d943318e8ba915e7a7aaeeb224ec56e4b0cd8b01))
* **tests:** force stub market rates provider in conftest ([#1383](https://github.com/italofelipe/auraxis-api/issues/1383)) ([b9ae998](https://github.com/italofelipe/auraxis-api/commit/b9ae9989cf9933e5707e677c4cf710db9cd80010)), closes [#1382](https://github.com/italofelipe/auraxis-api/issues/1382)

## [1.48.0](https://github.com/italofelipe/auraxis-api/compare/v1.47.0...v1.48.0) (2026-05-22)


### Features

* **agent:** telemetry capture + artifact upload in agent-implement workflow (R2/3.3a) ([#1355](https://github.com/italofelipe/auraxis-api/issues/1355)) ([503f40b](https://github.com/italofelipe/auraxis-api/commit/503f40b081231cc4ccf592a591de32401430c80b)), closes [#1354](https://github.com/italofelipe/auraxis-api/issues/1354)
* **agent:** telemetry capture + artifact upload in qa and watchdog workflows (R2/3.3b) ([#1356](https://github.com/italofelipe/auraxis-api/issues/1356)) ([210c656](https://github.com/italofelipe/auraxis-api/commit/210c6564c31bf9b49039181db5222db56a98eaa6))
* **sentry:** env-aware traces_sample_rate auto-default + dev setup guidance (R2/3.1c) ([#1353](https://github.com/italofelipe/auraxis-api/issues/1353)) ([23060b2](https://github.com/italofelipe/auraxis-api/commit/23060b2a2e9f0ea1195dfa31d2c5dfe71bbd2c47)), closes [#1352](https://github.com/italofelipe/auraxis-api/issues/1352)

## [1.47.0](https://github.com/italofelipe/auraxis-api/compare/v1.46.1...v1.47.0) (2026-05-22)


### Features

* **ai:** add monthly report workflow ([#1351](https://github.com/italofelipe/auraxis-api/issues/1351)) ([c79bd2e](https://github.com/italofelipe/auraxis-api/commit/c79bd2e2ab985c6deef8b20bd5459b78ec60025d))
* **ai:** expand daily insight snapshots by domain ([#1349](https://github.com/italofelipe/auraxis-api/issues/1349)) ([cc929b4](https://github.com/italofelipe/auraxis-api/commit/cc929b4c8385028f15d73dc0ab88dde9c78fabec))

## [1.46.1](https://github.com/italofelipe/auraxis-api/compare/v1.46.0...v1.46.1) (2026-05-22)


### Bug Fixes

* **ai:** honor user timezone for insight periods ([#1347](https://github.com/italofelipe/auraxis-api/issues/1347)) ([5aa6372](https://github.com/italofelipe/auraxis-api/commit/5aa637209dc7816160d0a18491fe1081586b437e))
* **auth:** harden email confirmation contract ([#1345](https://github.com/italofelipe/auraxis-api/issues/1345)) ([2d4de96](https://github.com/italofelipe/auraxis-api/commit/2d4de9613d9c71eee8539a375d1a87867a86db2e))

## [1.46.0](https://github.com/italofelipe/auraxis-api/compare/v1.45.0...v1.46.0) (2026-05-21)


### Features

* **auth:** /auth/email/confirm emit JWT + refresh cookie (magic-link login) ([#1339](https://github.com/italofelipe/auraxis-api/issues/1339)) ([1c48342](https://github.com/italofelipe/auraxis-api/commit/1c4834203d5542a73886fd2331b208924f67e0e0))


### Bug Fixes

* **config:** register EMAIL_CONFIRMATION_FRONTEND_URL in Config class ([#1337](https://github.com/italofelipe/auraxis-api/issues/1337)) ([1ab4a86](https://github.com/italofelipe/auraxis-api/commit/1ab4a86541cf93ba05a2e99e9574f8f258f51170))

## [1.45.0](https://github.com/italofelipe/auraxis-api/compare/v1.44.1...v1.45.0) (2026-05-21)


### Features

* **auth:** D-7/D-1 email verification reminders via cron job ([8eb32bd](https://github.com/italofelipe/auraxis-api/commit/8eb32bd8de3d48822c61b6d72d7ebdb5a815496b))
* **auth:** expand [@require](https://github.com/require)_email_verified to goal/wallet/budget/simulation/credit_card mutations ([69e6415](https://github.com/italofelipe/auraxis-api/commit/69e64159c53b88aeafcf84e0acbd97e5a02191ae))


### Bug Fixes

* **emails:** URL fallback canônico + templates v3 Market Pulse ([9811b3d](https://github.com/italofelipe/auraxis-api/commit/9811b3df4f1692dece1dd6a948cb32abba03c482))

## [1.44.1](https://github.com/italofelipe/auraxis-api/compare/v1.44.0...v1.44.1) (2026-05-20)


### Bug Fixes

* **deploy:** gate rollback only on deploy-critical failures (P0) ([#1322](https://github.com/italofelipe/auraxis-api/issues/1322)) ([eaf045c](https://github.com/italofelipe/auraxis-api/commit/eaf045c74710d91c3b0d75d498556205bdd5442c))

## [1.44.0](https://github.com/italofelipe/auraxis-api/compare/v1.43.0...v1.44.0) (2026-05-19)


### Features

* **ai:** add deterministic insight health scoring ([#1318](https://github.com/italofelipe/auraxis-api/issues/1318)) ([e1e3fcd](https://github.com/italofelipe/auraxis-api/commit/e1e3fcd84a022cb79a62f892fe64c223db058e9a))
* **ai:** expose audit preview dossier export ([#1317](https://github.com/italofelipe/auraxis-api/issues/1317)) ([cc2733a](https://github.com/italofelipe/auraxis-api/commit/cc2733aee8ce0ea075306838f1dc2577e29dde09))
* **ai:** govern insight generation cost ([#1319](https://github.com/italofelipe/auraxis-api/issues/1319)) ([81885ac](https://github.com/italofelipe/auraxis-api/commit/81885acfa5ee28b26873cfe4019a87c577a803a7))
* **ai:** persist ai insight runs ([#1315](https://github.com/italofelipe/auraxis-api/issues/1315)) ([ed3bfe5](https://github.com/italofelipe/auraxis-api/commit/ed3bfe58d7e00ed1709f7b2896b42cfc58ebf0fc))

## [1.43.0](https://github.com/italofelipe/auraxis-api/compare/v1.42.0...v1.43.0) (2026-05-18)


### Features

* **ai-insights:** track generation deltas ([#1303](https://github.com/italofelipe/auraxis-api/issues/1303)) ([2e15dc9](https://github.com/italofelipe/auraxis-api/commit/2e15dc9bb9eca6b372d79625aa3e71c4a3d9d04d))

## [1.42.0](https://github.com/italofelipe/auraxis-api/compare/v1.41.0...v1.42.0) (2026-05-18)


### Features

* **ai-insights:** enforce dimension↔evidence consistency per item ([#1300](https://github.com/italofelipe/auraxis-api/issues/1300)) ([#1302](https://github.com/italofelipe/auraxis-api/issues/1302)) ([40e12f5](https://github.com/italofelipe/auraxis-api/commit/40e12f55a78d25812ca263208b7cd95cbc5980dc))
* **ai-insights:** MVP-3 — dimension, credit_cards section, extended comparisons + GraphQL parity ([#1287](https://github.com/italofelipe/auraxis-api/issues/1287) [#1288](https://github.com/italofelipe/auraxis-api/issues/1288)) ([#1296](https://github.com/italofelipe/auraxis-api/issues/1296)) ([6b8d178](https://github.com/italofelipe/auraxis-api/commit/6b8d178a28931924a9e56e63daa415632be87afe))
* **ai-insights:** observability + snapshot guardrails + metadata (Sprint 5 [#1289](https://github.com/italofelipe/auraxis-api/issues/1289)) ([#1297](https://github.com/italofelipe/auraxis-api/issues/1297)) ([438970c](https://github.com/italofelipe/auraxis-api/commit/438970ccd3caecca007e1da8d111608040a4b35d))
* **ai-insights:** wallet section + CDI/IPCA benchmark + investor profile diagnosis ([#1243](https://github.com/italofelipe/auraxis-api/issues/1243)) ([#1298](https://github.com/italofelipe/auraxis-api/issues/1298)) ([48a0d66](https://github.com/italofelipe/auraxis-api/commit/48a0d66bef7b872876286f3f0dd8ade5f1c27b9c))
* **credit-card:** Hub de Cartões enriquecido + bill cycle + utilization (Sprint 1 MVP-3) ([#1294](https://github.com/italofelipe/auraxis-api/issues/1294)) ([02eaaf7](https://github.com/italofelipe/auraxis-api/commit/02eaaf74f34abb5bb0f80163325411c75bcfc529))

## [1.41.0](https://github.com/italofelipe/auraxis-api/compare/v1.40.1...v1.41.0) (2026-05-17)


### Features

* **credit-card:** bill cycle service with compute_bill_cycle + utili… ([#1290](https://github.com/italofelipe/auraxis-api/issues/1290)) ([19dd2a0](https://github.com/italofelipe/auraxis-api/commit/19dd2a02f3d18f9c33ed1a73d12377422bde96fb)), closes [#1284](https://github.com/italofelipe/auraxis-api/issues/1284)


### Bug Fixes

* **security:** retry com backoff no download do osv-scanner (502 transiente) ([#1292](https://github.com/italofelipe/auraxis-api/issues/1292)) ([e4b8391](https://github.com/italofelipe/auraxis-api/commit/e4b8391c49d355fd7ef9bc5225c1bbd03fe71939)), closes [#1291](https://github.com/italofelipe/auraxis-api/issues/1291)

## [1.40.1](https://github.com/italofelipe/auraxis-api/compare/v1.40.0...v1.40.1) (2026-05-17)


### Bug Fixes

* **billing:** grant founder premium entitlement ([#1282](https://github.com/italofelipe/auraxis-api/issues/1282)) ([9e77eaa](https://github.com/italofelipe/auraxis-api/commit/9e77eaa32c0528502b3087243f62aebd4fe16c84))

## [1.40.0](https://github.com/italofelipe/auraxis-api/compare/v1.39.0...v1.40.0) (2026-05-17)


### Features

* **ai:** add period-aware financial insight generation ([#1278](https://github.com/italofelipe/auraxis-api/issues/1278)) ([7044abd](https://github.com/italofelipe/auraxis-api/commit/7044abd191d1af67f046c74a3644b860174103ea))
* **ai:** align insight history and batches ([#1280](https://github.com/italofelipe/auraxis-api/issues/1280)) ([24bc38b](https://github.com/italofelipe/auraxis-api/commit/24bc38b7822778f0bb50e50ea14b3d328483e98f))


### Bug Fixes

* **ai:** support RDS compose in insights job ([#1281](https://github.com/italofelipe/auraxis-api/issues/1281)) ([7e115cf](https://github.com/italofelipe/auraxis-api/commit/7e115cf0fa8f33d03e387867aedd9acc03319f7c))

## [1.39.0](https://github.com/italofelipe/auraxis-api/compare/v1.38.1...v1.39.0) (2026-05-17)


### Features

* **ai:** add financial insight context builder ([#1273](https://github.com/italofelipe/auraxis-api/issues/1273)) ([a102467](https://github.com/italofelipe/auraxis-api/commit/a102467b2888e05aa9ff177e0b78421e66027452))
* **consent:** alembic migration — create consents table ([c58bde2](https://github.com/italofelipe/auraxis-api/commit/c58bde2e46034d6a4afd3d50ff1531304eb851e2)), closes [#1259](https://github.com/italofelipe/auraxis-api/issues/1259)
* **consent:** marshmallow schemas + service ([b9a306e](https://github.com/italofelipe/auraxis-api/commit/b9a306e08486ac1a033ce69591d75c1f91d55d0b)), closes [#1259](https://github.com/italofelipe/auraxis-api/issues/1259)
* **consent:** model + ConsentKind/Action/Source enums ([70cf376](https://github.com/italofelipe/auraxis-api/commit/70cf376829ff65c37d21bccd1c6d4b1c5b9058a8)), closes [#1259](https://github.com/italofelipe/auraxis-api/issues/1259)
* **consent:** register in LGPD registry ([947f2b4](https://github.com/italofelipe/auraxis-api/commit/947f2b49d4ef4be0fcc5c9755cbce1e2ade7b9c4)), closes [#1259](https://github.com/italofelipe/auraxis-api/issues/1259)
* **consent:** REST endpoints (GET/POST/DELETE /me/consents) ([d48af07](https://github.com/italofelipe/auraxis-api/commit/d48af0715b5ce608b75ede8669cc18859ca980fb)), closes [#1259](https://github.com/italofelipe/auraxis-api/issues/1259)
* **lgpd:** AI minimization, consent gate e audit redaction (Closes [#1258](https://github.com/italofelipe/auraxis-api/issues/1258)) ([14ce9f8](https://github.com/italofelipe/auraxis-api/commit/14ce9f808a5dd4265ee306187194878ce6fffe20))
* **lgpd:** ai_lgpd module — consent gate + minimisation + audit redaction ([#1258](https://github.com/italofelipe/auraxis-api/issues/1258)) ([909ffa9](https://github.com/italofelipe/auraxis-api/commit/909ffa96e0ea8e238f95ca957c8e5a6482cc266d))
* **lgpd:** consentimentos versionados — model + endpoints + registry (Closes [#1259](https://github.com/italofelipe/auraxis-api/issues/1259)) ([ccec2ff](https://github.com/italofelipe/auraxis-api/commit/ccec2ff21c732fd378b18dafac3086da011034e3))
* **lgpd:** deleção integral auditável via REGISTRY (Closes [#1257](https://github.com/italofelipe/auraxis-api/issues/1257)) ([315da83](https://github.com/italofelipe/auraxis-api/commit/315da83718259d4fe3c0c6b4b3b88bbfe22aa7f9))
* **lgpd:** deletion service — registry-driven strategy dispatcher ([57a297f](https://github.com/italofelipe/auraxis-api/commit/57a297fbbaed58d631954455318ca92f2f610725)), closes [#1257](https://github.com/italofelipe/auraxis-api/issues/1257)
* **lgpd:** export service using REGISTRY (build_user_export) ([f306146](https://github.com/italofelipe/auraxis-api/commit/f306146ad095d667aa98e1db9f13c44e280fd322)), closes [#1256](https://github.com/italofelipe/auraxis-api/issues/1256)
* **lgpd:** exportação e portabilidade de dados — GET /user/me/export (Closes [#1256](https://github.com/italofelipe/auraxis-api/issues/1256)) ([fe97ae5](https://github.com/italofelipe/auraxis-api/commit/fe97ae5196a8ca3741d29ee577714ef79f5151dd))
* **lgpd:** GET /user/me/export endpoint ([16e3da2](https://github.com/italofelipe/auraxis-api/commit/16e3da26f9fc9d90f68a5d4bcfd73d6592c815c0)), closes [#1256](https://github.com/italofelipe/auraxis-api/issues/1256)
* **lgpd:** map AIConsentRequiredError → 403 AI_CONSENT_REQUIRED in AI controllers ([#1258](https://github.com/italofelipe/auraxis-api/issues/1258)) ([6fc6270](https://github.com/italofelipe/auraxis-api/commit/6fc62707bd779ea6e1f308616a1b673af34b9fc1))
* **lgpd:** registry module — entities, rules, deletion strategies ([c7d6bd6](https://github.com/italofelipe/auraxis-api/commit/c7d6bd6d33ace84b72bc5d3c0f43e6cc048011e7)), closes [#1255](https://github.com/italofelipe/auraxis-api/issues/1255)
* **lgpd:** registry técnico de dados pessoais (Closes [#1255](https://github.com/italofelipe/auraxis-api/issues/1255)) ([228b915](https://github.com/italofelipe/auraxis-api/commit/228b915e878463b172d003c9e502cafcfa830a35))
* **lgpd:** wire AI consent gate + prompt minimisation into advisory service ([#1258](https://github.com/italofelipe/auraxis-api/issues/1258)) ([0aa5749](https://github.com/italofelipe/auraxis-api/commit/0aa574911a4f53587e14427364183137f3ff6877))


### Bug Fixes

* **ai:** count insight quota only after successful generation ([#1265](https://github.com/italofelipe/auraxis-api/issues/1265)) ([8c61d67](https://github.com/italofelipe/auraxis-api/commit/8c61d673ab6ee79079e63caf45e5dffd59ca14c3))
* **ai:** enforce structured spending insights ([#1268](https://github.com/italofelipe/auraxis-api/issues/1268)) ([3d8a196](https://github.com/italofelipe/auraxis-api/commit/3d8a196e632f524a44a6cb8e89b80cc5faae472e))
* **ci:** allowlist synthetic JWT fixture from gitleaks ([96d25c4](https://github.com/italofelipe/auraxis-api/commit/96d25c4428343afbba46a2d3f112aea6a8b55e96)), closes [#1258](https://github.com/italofelipe/auraxis-api/issues/1258)
* **ci:** gitleaks .gitleaksignore for synthetic JWT in commit history ([a234a03](https://github.com/italofelipe/auraxis-api/commit/a234a03ee7650cca36eebcf501dbfba8b173ae98)), closes [#1258](https://github.com/italofelipe/auraxis-api/issues/1258)
* **consent:** persist enum.value (lowercase) not enum.name (uppercase) ([f2e2a78](https://github.com/italofelipe/auraxis-api/commit/f2e2a7892976d34ed4d169682c7a520326615f5a)), closes [#1259](https://github.com/italofelipe/auraxis-api/issues/1259)
* **lgpd:** drop spurious branch in _minimize_description (Sonar S3516) ([993d502](https://github.com/italofelipe/auraxis-api/commit/993d502538b7babeb31f85045fabb27bd3a685bd)), closes [#1258](https://github.com/italofelipe/auraxis-api/issues/1258)
* **lgpd:** exclude credential/token columns from export (security) ([fb56f9c](https://github.com/italofelipe/auraxis-api/commit/fb56f9cea11eebdb1d80898e7a0eae8e58485677)), closes [#1256](https://github.com/italofelipe/auraxis-api/issues/1256)
* **lgpd:** iterate mapper.column_attrs — Column.key is not the Python attr ([1ed83e7](https://github.com/italofelipe/auraxis-api/commit/1ed83e7fb8554239a29e5b1254745ad949d2cd58)), closes [#1256](https://github.com/italofelipe/auraxis-api/issues/1256)
* **lgpd:** per-entity isolation in export — never 500 the whole pack ([c5e8b6b](https://github.com/italofelipe/auraxis-api/commit/c5e8b6b31feaa1097b2eb27ca2b5f64de26b0e12)), closes [#1256](https://github.com/italofelipe/auraxis-api/issues/1256)
* **lgpd:** use col.key for attr access — handle remapped column names ([96db932](https://github.com/italofelipe/auraxis-api/commit/96db93204099fab3e7221ca9bdca83638b09832b)), closes [#1256](https://github.com/italofelipe/auraxis-api/issues/1256)

## [1.38.1](https://github.com/italofelipe/auraxis-api/compare/v1.38.0...v1.38.1) (2026-05-16)


### Bug Fixes

* **deploy:** apply alembic migrations + validate rollback target URI ([#1261](https://github.com/italofelipe/auraxis-api/issues/1261)) ([84f4e75](https://github.com/italofelipe/auraxis-api/commit/84f4e75f8ebf05f86e9af5b9f62aebfd77bce49c)), closes [#1252](https://github.com/italofelipe/auraxis-api/issues/1252) [#1253](https://github.com/italofelipe/auraxis-api/issues/1253)
* **infra:** make entrypoint RDS-aware to unblock prod deploys ([#1254](https://github.com/italofelipe/auraxis-api/issues/1254)) ([#1260](https://github.com/italofelipe/auraxis-api/issues/1260)) ([ce0695a](https://github.com/italofelipe/auraxis-api/commit/ce0695abdecffcf5d2e12ff52318ea196c53b21a))

## [1.38.0](https://github.com/italofelipe/auraxis-api/compare/v1.37.0...v1.38.0) (2026-05-12)


### Features

* **ai:** enriquecer daily insight com contexto de metas e orçamento geral ([#1235](https://github.com/italofelipe/auraxis-api/issues/1235)) ([#1238](https://github.com/italofelipe/auraxis-api/issues/1238)) ([4d8bbc6](https://github.com/italofelipe/auraxis-api/commit/4d8bbc676740fffc0136fbfba66d4ac66f437104))
* **ai:** TransactionCategory + Budget category + weekly/recap cross-domain insights ([#1239](https://github.com/italofelipe/auraxis-api/issues/1239) [#1240](https://github.com/italofelipe/auraxis-api/issues/1240) [#1241](https://github.com/italofelipe/auraxis-api/issues/1241) [#1242](https://github.com/italofelipe/auraxis-api/issues/1242)) ([#1244](https://github.com/italofelipe/auraxis-api/issues/1244)) ([418dc05](https://github.com/italofelipe/auraxis-api/commit/418dc055a6a53be462e2fde2b6c1009018f591b2))
* **goals:** GoalContribution tracking — registro automático de aportes em metas ([#1234](https://github.com/italofelipe/auraxis-api/issues/1234)) ([#1236](https://github.com/italofelipe/auraxis-api/issues/1236)) ([1bf6091](https://github.com/italofelipe/auraxis-api/commit/1bf6091b60fe202909082c55ff7c69983b029131))

## [1.37.0](https://github.com/italofelipe/auraxis-api/compare/v1.36.0...v1.37.0) (2026-05-12)


### Features

* **ai:** AIInsight model + migration ai2 ([#1227](https://github.com/italofelipe/auraxis-api/issues/1227)) ([#1229](https://github.com/italofelipe/auraxis-api/issues/1229)) ([37ab0c3](https://github.com/italofelipe/auraxis-api/commit/37ab0c3e92ca2c46c4814177dfc40a2292c31232))
* **ai:** apply daily rate limit decorator to /ai/insights/* endpoints ([dfca463](https://github.com/italofelipe/auraxis-api/commit/dfca463682fe022d7c08b9d46933fe8e269b1d36))
* **ai:** daily rate limit para insights manuais — 2x/dia por usuário Premium ([#1214](https://github.com/italofelipe/auraxis-api/issues/1214)) ([8e55508](https://github.com/italofelipe/auraxis-api/commit/8e55508fa17e406193bad702ff906cf0269887dd))
* **ai:** Flask CLI commands for weekly and monthly AI insights batch jobs ([934da99](https://github.com/italofelipe/auraxis-api/commit/934da9976c03dfb8a9b1ac1622a7d98d43da2e32))
* **ai:** jobs semanal e mensal de insights — CLI + SSM + workflows ([#1215](https://github.com/italofelipe/auraxis-api/issues/1215), [#1216](https://github.com/italofelipe/auraxis-api/issues/1216)) ([830691b](https://github.com/italofelipe/auraxis-api/commit/830691bf8528d77326099007ecfcb8a0fc669cde))
* **ai:** per-user daily rate limit middleware for AI insights endpoints ([356f6a8](https://github.com/italofelipe/auraxis-api/commit/356f6a8c875ab90174ebd320f132137da98a680c))
* **ai:** persistência de insights + context injection + recap + GET history ([#1228](https://github.com/italofelipe/auraxis-api/issues/1228)) ([#1230](https://github.com/italofelipe/auraxis-api/issues/1230)) ([c3bc94a](https://github.com/italofelipe/auraxis-api/commit/c3bc94a77f63e4e6b6d246c6ebeda8e8836c19a9))
* **ai:** SSM script, GH Actions workflows, tests for weekly+monthly batch jobs ([7e1914a](https://github.com/italofelipe/auraxis-api/commit/7e1914adac030f2697ea567983547a4339c43477))
* **graphql:** AIInsightType + aiInsightHistory query — GraphQL parity ([#1233](https://github.com/italofelipe/auraxis-api/issues/1233)) ([26a2de6](https://github.com/italofelipe/auraxis-api/commit/26a2de6ab82ff977576d4f7edd3152a40d7d20b5)), closes [#1231](https://github.com/italofelipe/auraxis-api/issues/1231)


### Bug Fixes

* **infra:** default MIGRATE_ON_START to false in prod ([#1225](https://github.com/italofelipe/auraxis-api/issues/1225)) ([b1a9912](https://github.com/italofelipe/auraxis-api/commit/b1a9912d701162f6ec8d902e0801db963d0a5f79))

## [1.36.0](https://github.com/italofelipe/auraxis-api/compare/v1.35.2...v1.36.0) (2026-05-10)


### Features

* **notifications:** gate premium em reminders + notificacao analise pronta ([#1212](https://github.com/italofelipe/auraxis-api/issues/1212)) ([51614a0](https://github.com/italofelipe/auraxis-api/commit/51614a0bd4aae6401d8bac595893a9fc4428eeed))

## [1.35.2](https://github.com/italofelipe/auraxis-api/compare/v1.35.1...v1.35.2) (2026-05-10)


### Bug Fixes

* **pricing:** atualizar preço canônico premium para R$29,90/mês (ADR [#669](https://github.com/italofelipe/auraxis-api/issues/669)) ([#1208](https://github.com/italofelipe/auraxis-api/issues/1208)) ([2ab7a5d](https://github.com/italofelipe/auraxis-api/commit/2ab7a5d89c5c2cdf677c2e44b0c192ff2293142b))

## [1.35.1](https://github.com/italofelipe/auraxis-api/compare/v1.35.0...v1.35.1) (2026-05-10)


### Bug Fixes

* **ci:** schemathesis 4.x API migration + pydantic &gt;=2.13.4 (closes Dependabot [#1123](https://github.com/italofelipe/auraxis-api/issues/1123)) ([#1203](https://github.com/italofelipe/auraxis-api/issues/1203)) ([d40f022](https://github.com/italofelipe/auraxis-api/commit/d40f02214b57d31ba6a75e565d17e97693ae421c))

## [1.35.0](https://github.com/italofelipe/auraxis-api/compare/v1.34.0...v1.35.0) (2026-05-10)


### Features

* **graphql/infra:** SQL coalescing + Postgres cleanup + GraphQL rate limit ([8c94821](https://github.com/italofelipe/auraxis-api/commit/8c94821eb077a3d62f5205dfd3f8f164f8d5eae0))
* **graphql:** add Bank Statement Import domain — [#1148](https://github.com/italofelipe/auraxis-api/issues/1148) ([0147130](https://github.com/italofelipe/auraxis-api/commit/01471306b718240a309c01ebe0c30b5fcff337cb))
* **graphql:** add missing domains — Account, Tags, Bank Statement ([a4de088](https://github.com/italofelipe/auraxis-api/commit/a4de088ccb5f6f40ab3577d984a165f2d70a26f8))


### Bug Fixes

* **graphql:** use TransactionStatus enum in coalesced status counts ([ee0dbda](https://github.com/italofelipe/auraxis-api/commit/ee0dbdacbef7128b12bf0aaaa875a73f71781201))
* **merge:** resolve conflicts — keep bank statement types and catalog entries ([78c133a](https://github.com/italofelipe/auraxis-api/commit/78c133ab2cef64a39da875f2bcdcce1b08b032e1))
* **merge:** resolve types.py conflict — take master (bank statement types) ([f78475b](https://github.com/italofelipe/auraxis-api/commit/f78475b5498a6fcd50613471d1f6824827d77517))
* **merge:** take master enum-based status counts in analytics service ([b7ae891](https://github.com/italofelipe/auraxis-api/commit/b7ae891fc465ba545d9b6995fd911d06eae6f0fd))


### Performance Improvements

* **graphql:** coalesce dashboard SQL queries 4 -&gt; 2 ([d12a13c](https://github.com/italofelipe/auraxis-api/commit/d12a13cc8cf035696e0fcce1dbf6614e9550b121)), closes [#1156](https://github.com/italofelipe/auraxis-api/issues/1156)
* **graphql:** coalesce dashboard SQL queries 4 -&gt; 2 ([c721293](https://github.com/italofelipe/auraxis-api/commit/c72129350af37d598fb979993cb1a5439926a0a8)), closes [#1156](https://github.com/italofelipe/auraxis-api/issues/1156)

## [1.34.0](https://github.com/italofelipe/auraxis-api/compare/v1.33.0...v1.34.0) (2026-05-09)


### Features

* **audit:** record entity-delete audit events for goals, wallet, subscriptions ([#1160](https://github.com/italofelipe/auraxis-api/issues/1160)) ([ef89098](https://github.com/italofelipe/auraxis-api/commit/ef890984cf9d72ff43c39bf5189a20e277f0b113))
* **ci:** production watchdog ([#1191](https://github.com/italofelipe/auraxis-api/issues/1191)) ([f7753a7](https://github.com/italofelipe/auraxis-api/commit/f7753a7e0e24d2f7403d4038d51ad1475d89523e))
* **deploy:** Sentry canary check + auto-rollback ([#1194](https://github.com/italofelipe/auraxis-api/issues/1194)) ([0f585f9](https://github.com/italofelipe/auraxis-api/commit/0f585f9cfb14e24e594780315433827b43def41d))
* **dx:** P2 DX initiatives from PR [#1174](https://github.com/italofelipe/auraxis-api/issues/1174) post-mortem (INI-3/4) ([#1182](https://github.com/italofelipe/auraxis-api/issues/1182)) ([1649592](https://github.com/italofelipe/auraxis-api/commit/1649592bdd22ff602889d72b604b3d21ce2118e5))
* **entitlements:** add focus_mode to premium plan ([#1117](https://github.com/italofelipe/auraxis-api/issues/1117)) ([893820f](https://github.com/italofelipe/auraxis-api/commit/893820fa0a6a44b5fc7fb22098bc24fff71d6e78))
* **graphql:** /graphql/playground — GraphiQL endpoint (feature-flagged, admin-only) ([#1165](https://github.com/italofelipe/auraxis-api/issues/1165)) ([e681db8](https://github.com/italofelipe/auraxis-api/commit/e681db8d64284b208b80e2bff7af933e51709af2))
* **graphql:** CI breaking-change detection + OTel tracing + canonical MutationPayload ([#1170](https://github.com/italofelipe/auraxis-api/issues/1170)) ([2be6539](https://github.com/italofelipe/auraxis-api/commit/2be6539fa130b408fdc219fb708ef9494295197b))
* **graphql:** enforce enum types on mutation inputs (status/type/asset_class/billing_cycle) ([#1159](https://github.com/italofelipe/auraxis-api/issues/1159)) ([eb13b16](https://github.com/italofelipe/auraxis-api/commit/eb13b16b3484da79971241f8124032839ff99f7a))
* **graphql:** per-field complexity weights — apply to split module structure ([#1167](https://github.com/italofelipe/auraxis-api/issues/1167)) ([2481ba6](https://github.com/italofelipe/auraxis-api/commit/2481ba6e21fd9059ad03a4b4f6bd2eeec01ad21a)), closes [#1154](https://github.com/italofelipe/auraxis-api/issues/1154)
* **graphql:** structured resolver logging + parameterized auth-required regression test ([#1161](https://github.com/italofelipe/auraxis-api/issues/1161)) ([c462f53](https://github.com/italofelipe/auraxis-api/commit/c462f531393026498abd5abab5afc70919921374))
* **graphql:** Tags + Accounts GraphQL domains — REST↔GraphQL parity ([#1148](https://github.com/italofelipe/auraxis-api/issues/1148)) ([#1183](https://github.com/italofelipe/auraxis-api/issues/1183)) ([5dfddbe](https://github.com/italofelipe/auraxis-api/commit/5dfddbeb80e335d666116a73a5c6d83f5eb9c51d))
* **infra:** migrate Docker build from EC2 to GitHub Actions + GHCR ([#1171](https://github.com/italofelipe/auraxis-api/issues/1171)) ([#1172](https://github.com/italofelipe/auraxis-api/issues/1172)) ([e08e3c5](https://github.com/italofelipe/auraxis-api/commit/e08e3c54973eea58eaaa59d440ab020b8d6a540c))
* **notifications:** push subscription registration (Expo + Web Push) ([#1174](https://github.com/italofelipe/auraxis-api/issues/1174)) ([4c34cdc](https://github.com/italofelipe/auraxis-api/commit/4c34cdc4067b8cbd07345e9f6bebc11fb9ad1e8e))
* **simulations:** allowlist aposentadoria + desconto-markup in TOOLS_REGISTRY ([#1132](https://github.com/italofelipe/auraxis-api/issues/1132)) ([3cb8147](https://github.com/italofelipe/auraxis-api/commit/3cb8147408ac63c1bbf0efa9f3e6e19347a8df24))
* **simulations:** canonical generic /simulations endpoint ([#1128](https://github.com/italofelipe/auraxis-api/issues/1128)) ([#1130](https://github.com/italofelipe/auraxis-api/issues/1130)) ([2124a9e](https://github.com/italofelipe/auraxis-api/commit/2124a9e270561be906e1a78b07e2c93c59df541e))
* **user:** avatar upload endpoint + S3 storage ([#1173](https://github.com/italofelipe/auraxis-api/issues/1173)) ([962ce6e](https://github.com/italofelipe/auraxis-api/commit/962ce6e76de7200b3d7c2865626e7451c31a3658))


### Bug Fixes

* **graphql:** replace Float with DecimalScalar on monetary fields, paginate tickers ([#1158](https://github.com/italofelipe/auraxis-api/issues/1158)) ([e6dab69](https://github.com/italofelipe/auraxis-api/commit/e6dab693bcff0ae959d88696e76c252f98a612bb))
* **jobs:** scheduled job observability — DIAG_EOF delimiter + audit-events error handling ([#1168](https://github.com/italofelipe/auraxis-api/issues/1168)) ([f600e83](https://github.com/italofelipe/auraxis-api/commit/f600e835f4509def018cd14ccc9e1d50b1ebf8d2))
* **tags:** accept hex with alpha channel and normalize ([#1125](https://github.com/italofelipe/auraxis-api/issues/1125)) ([347450d](https://github.com/italofelipe/auraxis-api/commit/347450dd08db94595e192dfb90a0e194ab9fa890))

## [1.33.0](https://github.com/italofelipe/auraxis-api/compare/v1.32.0...v1.33.0) (2026-04-20)


### Features

* **dashboard:** B13 — contrato de resumo semanal com comparativo e série temporal ([#1104](https://github.com/italofelipe/auraxis-api/issues/1104)) ([7ea7a49](https://github.com/italofelipe/auraxis-api/commit/7ea7a492297a6424b349f6741b7ae6514182be99))

## [1.32.0](https://github.com/italofelipe/auraxis-api/compare/v1.31.0...v1.32.0) (2026-04-19)


### Features

* **quality:** n+1 gate, hypothesis property tests, REST contract doc ([#1027](https://github.com/italofelipe/auraxis-api/issues/1027) [#1054](https://github.com/italofelipe/auraxis-api/issues/1054) [#1087](https://github.com/italofelipe/auraxis-api/issues/1087)) ([#1096](https://github.com/italofelipe/auraxis-api/issues/1096)) ([a7d5d14](https://github.com/italofelipe/auraxis-api/commit/a7d5d14447d076f84b20cb7899c2b0f686337ddb))


### Bug Fixes

* **jobs:** audit-retention SSM cd bug + reminder DLQ fallback ([#989](https://github.com/italofelipe/auraxis-api/issues/989) [#1081](https://github.com/italofelipe/auraxis-api/issues/1081)) ([#1094](https://github.com/italofelipe/auraxis-api/issues/1094)) ([ab7dd14](https://github.com/italofelipe/auraxis-api/commit/ab7dd14b6053600601fe5105e5f9d99fcc6cf717))

## [1.31.0](https://github.com/italofelipe/auraxis-api/compare/v1.30.0...v1.31.0) (2026-04-18)


### Features

* **arc-api-01-02:** MarketDataProvider port + async outbound queue (RQ/Redis) ([#1093](https://github.com/italofelipe/auraxis-api/issues/1093)) ([4d95f99](https://github.com/italofelipe/auraxis-api/commit/4d95f99dd9b83b871a5d946931a135d7c73c640a))
* **arc-api-03:** correlation-ID middleware end-to-end (X-Request-ID) ([#1089](https://github.com/italofelipe/auraxis-api/issues/1089)) ([f7d32f5](https://github.com/italofelipe/auraxis-api/commit/f7d32f54c85c4b426801a753075bd9584011df9d))

## [1.30.0](https://github.com/italofelipe/auraxis-api/compare/v1.29.0...v1.30.0) (2026-04-15)


### Features

* **governance:** entitlement matrix documentation + CI enforcement ([#1057](https://github.com/italofelipe/auraxis-api/issues/1057)) ([#1079](https://github.com/italofelipe/auraxis-api/issues/1079)) ([b5f14f9](https://github.com/italofelipe/auraxis-api/commit/b5f14f965816dfea459c4a6948fbf9ad7c689b1b))
* **observability:** cache hit/miss/invalidation Prometheus metrics ([#1056](https://github.com/italofelipe/auraxis-api/issues/1056)) ([#1078](https://github.com/italofelipe/auraxis-api/issues/1078)) ([a17b821](https://github.com/italofelipe/auraxis-api/commit/a17b821b54a27f164c01b82095566f9bac2c8a63))

## [1.29.0](https://github.com/italofelipe/auraxis-api/compare/v1.28.0...v1.29.0) (2026-04-15)


### Features

* **shared-entries:** optimistic locking via version column ([#1053](https://github.com/italofelipe/auraxis-api/issues/1053)) ([#1074](https://github.com/italofelipe/auraxis-api/issues/1074)) ([76a5a74](https://github.com/italofelipe/auraxis-api/commit/76a5a74405716d660500284a4e0fa170475b9084))


### Performance Improvements

* **queries:** query-count regression gate — CI enforcement for N+1 prevention ([#1054](https://github.com/italofelipe/auraxis-api/issues/1054)) ([#1075](https://github.com/italofelipe/auraxis-api/issues/1075)) ([384249c](https://github.com/italofelipe/auraxis-api/commit/384249caf46b8c93d6db0710b2b8f04e65b7aa1d))

## [1.28.0](https://github.com/italofelipe/auraxis-api/compare/v1.27.1...v1.28.0) (2026-04-15)


### Features

* **resilience:** email DLQ — zero-loss retry for notifications ([#1049](https://github.com/italofelipe/auraxis-api/issues/1049)) ([#1069](https://github.com/italofelipe/auraxis-api/issues/1069)) ([c6c7b0b](https://github.com/italofelipe/auraxis-api/commit/c6c7b0b0589b432f84d38a6e913212e3a0c452b6))
* **resilience:** login guard — in-memory failover when Redis down at runtime ([#1050](https://github.com/italofelipe/auraxis-api/issues/1050)) ([#1071](https://github.com/italofelipe/auraxis-api/issues/1071)) ([6239568](https://github.com/italofelipe/auraxis-api/commit/6239568450d23766d2e83c2c978b02aca11ced64))
* **retention:** audit event auto-retention — scheduled job, BRIN index, Prometheus counter ([#1051](https://github.com/italofelipe/auraxis-api/issues/1051)) ([#1072](https://github.com/italofelipe/auraxis-api/issues/1072)) ([73b53a9](https://github.com/italofelipe/auraxis-api/commit/73b53a94f3d970a036fd89064c64764cf83bea8d))

## [1.27.1](https://github.com/italofelipe/auraxis-api/compare/v1.27.0...v1.27.1) (2026-04-15)


### Bug Fixes

* **ops:** reminder-job — container health check + auto-recovery before dispatch ([#1066](https://github.com/italofelipe/auraxis-api/issues/1066)) ([c7b6974](https://github.com/italofelipe/auraxis-api/commit/c7b6974f4c9f3c134c81b45a00b357b7a0d9e2d0))

## [1.27.0](https://github.com/italofelipe/auraxis-api/compare/v1.26.1...v1.27.0) (2026-04-15)


### Features

* **advisory:** AI advisory engine — GET /advisory/insights ([#1026](https://github.com/italofelipe/auraxis-api/issues/1026)) ([#1044](https://github.com/italofelipe/auraxis-api/issues/1044)) ([ffbec15](https://github.com/italofelipe/auraxis-api/commit/ffbec15ba06a723708110412e924d3c149781a72))
* **auth:** multi-device sessions with refresh token rotation ([#1028](https://github.com/italofelipe/auraxis-api/issues/1028)) ([#1045](https://github.com/italofelipe/auraxis-api/issues/1045)) ([8d1c092](https://github.com/italofelipe/auraxis-api/commit/8d1c092499648b03f0159cf6e3a1897a2ad2b10e))
* **dashboard:** survival index endpoint — GET /dashboard/survival-index ([#1024](https://github.com/italofelipe/auraxis-api/issues/1024)) ([#1041](https://github.com/italofelipe/auraxis-api/issues/1041)) ([ceceb3b](https://github.com/italofelipe/auraxis-api/commit/ceceb3b4220743b3b23069b98cde4008ee5562b8))
* **graphql:** deprecate REST-canonical mutations per H-P5.1 ownership decision [[#839](https://github.com/italofelipe/auraxis-api/issues/839)] ([#1036](https://github.com/italofelipe/auraxis-api/issues/1036)) ([72eb744](https://github.com/italofelipe/auraxis-api/commit/72eb7447cbaa79150dc79ecf270cf1af4a04bc3d))
* **transactions:** export endpoint CSV/PDF com entitlement export_pdf ([#1022](https://github.com/italofelipe/auraxis-api/issues/1022)) ([#1040](https://github.com/italofelipe/auraxis-api/issues/1040)) ([d19c214](https://github.com/italofelipe/auraxis-api/commit/d19c214cf025e128cfdec507da9d04ae0ccc80b3))


### Bug Fixes

* **graphql:** revert mutation deprecation — REST e GraphQL mantêm paridade total de CRUD [[#839](https://github.com/italofelipe/auraxis-api/issues/839)] ([#1038](https://github.com/italofelipe/auraxis-api/issues/1038)) ([39871a1](https://github.com/italofelipe/auraxis-api/commit/39871a1a2a50aacaf601e8b530f17f76d349572c))

## [1.26.1](https://github.com/italofelipe/auraxis-api/compare/v1.26.0...v1.26.1) (2026-04-13)


### Bug Fixes

* **auth:** revoke JWT tokens for soft-deleted users + billing canonical wiki ([#1030](https://github.com/italofelipe/auraxis-api/issues/1030)) ([4ca1aaf](https://github.com/italofelipe/auraxis-api/commit/4ca1aaf2fbe7df5032c2f14b96d1d3f3d044284a))

## [1.26.0](https://github.com/italofelipe/auraxis-api/compare/v1.25.1...v1.26.0) (2026-04-13)


### Features

* **h-p3.3:** branded email templates for D-7 and D-1 transaction reminders ([#1017](https://github.com/italofelipe/auraxis-api/issues/1017)) ([9595bb3](https://github.com/italofelipe/auraxis-api/commit/9595bb34c1a3a7d9a1856ee51d71ca81daa07f93))
* **postman:** POSTMAN-02 — generate collection from openapi.json ([#1002](https://github.com/italofelipe/auraxis-api/issues/1002)) ([c7989d6](https://github.com/italofelipe/auraxis-api/commit/c7989d687947e50fdcf6785c0daf1f494c820284))
* **postman:** POSTMAN-04 — push collection to Postman Cloud via API ([#1006](https://github.com/italofelipe/auraxis-api/issues/1006)) ([736c90c](https://github.com/italofelipe/auraxis-api/commit/736c90c723551e42d1d5e187f3359e4b963900d7)), closes [#966](https://github.com/italofelipe/auraxis-api/issues/966)
* **postman:** semantic contract tests + pre-commit gate ([#1014](https://github.com/italofelipe/auraxis-api/issues/1014)) ([35116fb](https://github.com/italofelipe/auraxis-api/commit/35116fb0b7354c77dc48ef0828befdf3ed335e12))


### Bug Fixes

* **reminders:** handle EmailProviderError + expose SSM output ([#989](https://github.com/italofelipe/auraxis-api/issues/989)) ([#1015](https://github.com/italofelipe/auraxis-api/issues/1015)) ([7e50eed](https://github.com/italofelipe/auraxis-api/commit/7e50eede09be3e30a6f642cd3401f3aa89229b0f))


### Performance Improvements

* **k6:** PERF-5 — k6 smoke baseline scripts and CI workflow ([#1005](https://github.com/italofelipe/auraxis-api/issues/1005)) ([2deef21](https://github.com/italofelipe/auraxis-api/commit/2deef21451b520fd643e2e46eb3ca170bf03bf65))

## [1.25.1](https://github.com/italofelipe/auraxis-api/compare/v1.25.0...v1.25.1) (2026-04-12)


### Performance Improvements

* **indexes:** PERF-1 — add ix_tags_user_id and ix_accounts_user_id migration ([#999](https://github.com/italofelipe/auraxis-api/issues/999)) ([7d7650f](https://github.com/italofelipe/auraxis-api/commit/7d7650f1a40286ee5473989c4bf950c2bbaaca9e))

## [1.25.0](https://github.com/italofelipe/auraxis-api/compare/v1.24.1...v1.25.0) (2026-04-12)


### Features

* **openapi:** POSTMAN-01 + POSTMAN-06 — CLI export + drift check ([#963](https://github.com/italofelipe/auraxis-api/issues/963), [#968](https://github.com/italofelipe/auraxis-api/issues/968)) ([#997](https://github.com/italofelipe/auraxis-api/issues/997)) ([753ba1d](https://github.com/italofelipe/auraxis-api/commit/753ba1d2785bf76809bed61a47c47e419bb6ee94))


### Performance Improvements

* **retry:** PERF-4 — add jitter + structured logging to retry wrapper ([#994](https://github.com/italofelipe/auraxis-api/issues/994)) ([210e085](https://github.com/italofelipe/auraxis-api/commit/210e085cbaed71e8a2dc7ca3d8916d17301f837f))

## [1.24.1](https://github.com/italofelipe/auraxis-api/compare/v1.24.0...v1.24.1) (2026-04-12)


### Bug Fixes

* **reminders:** add missing CLI command for dispatch-due-soon ([#989](https://github.com/italofelipe/auraxis-api/issues/989)) ([#992](https://github.com/italofelipe/auraxis-api/issues/992)) ([cfc016c](https://github.com/italofelipe/auraxis-api/commit/cfc016c49040a52341e8f1120644172bc7fbcd6e))

## [1.24.0](https://github.com/italofelipe/auraxis-api/compare/v1.23.0...v1.24.0) (2026-04-12)


### Features

* **auth:** sec-1 close dual-mode refresh_token — cookie-only policy flag + header opt-in ([#984](https://github.com/italofelipe/auraxis-api/issues/984)) ([245eb17](https://github.com/italofelipe/auraxis-api/commit/245eb179a238790ccc66bdcdbf7df381efb3128d))

## [1.23.0](https://github.com/italofelipe/auraxis-api/compare/v1.22.0...v1.23.0) (2026-04-11)


### Features

* **mvp1:** consolidate MVP-1 backend issues ([#886](https://github.com/italofelipe/auraxis-api/issues/886) [#835](https://github.com/italofelipe/auraxis-api/issues/835) [#836](https://github.com/italofelipe/auraxis-api/issues/836) [#840](https://github.com/italofelipe/auraxis-api/issues/840) [#841](https://github.com/italofelipe/auraxis-api/issues/841) [#839](https://github.com/italofelipe/auraxis-api/issues/839) [#838](https://github.com/italofelipe/auraxis-api/issues/838) [#701](https://github.com/italofelipe/auraxis-api/issues/701)) ([#953](https://github.com/italofelipe/auraxis-api/issues/953)) ([a19746e](https://github.com/italofelipe/auraxis-api/commit/a19746ecf8bf5750fded7045753de14da60695d7))


### Performance Improvements

* **db:** PERF-GAP-01 — composite indexes on hot query paths ([#948](https://github.com/italofelipe/auraxis-api/issues/948)) ([ce15bb0](https://github.com/italofelipe/auraxis-api/commit/ce15bb0562c0ce09799613c62448907f4470c2d9))
* **db:** PERF-GAP-02 — eager-load Wallet.operations in portfolio valuation ([#949](https://github.com/italofelipe/auraxis-api/issues/949)) ([6cf13c5](https://github.com/italofelipe/auraxis-api/commit/6cf13c5d01be1a7c197044a636a2c62da758aa28)), closes [#940](https://github.com/italofelipe/auraxis-api/issues/940)
* **services:** PERF-GAP-04 — retry + exponential backoff for BRAPI, Resend, Asaas ([#950](https://github.com/italofelipe/auraxis-api/issues/950)) ([0c2611a](https://github.com/italofelipe/auraxis-api/commit/0c2611a8124752449cd47482d06baf452e235300)), closes [#942](https://github.com/italofelipe/auraxis-api/issues/942)

## [1.22.0](https://github.com/italofelipe/auraxis-api/compare/v1.21.0...v1.22.0) (2026-04-10)


### Features

* **billing:** webhook audit log, rate limit, retry CLI — PAY-02/PAY-03 ([#916](https://github.com/italofelipe/auraxis-api/issues/916) [#917](https://github.com/italofelipe/auraxis-api/issues/917)) ([#931](https://github.com/italofelipe/auraxis-api/issues/931)) ([b79082c](https://github.com/italofelipe/auraxis-api/commit/b79082caf41a5a53ae5c64d0a0e184f8eb68f380))
* **goals:** portfolio-aware compound-interest goal projection ([#861](https://github.com/italofelipe/auraxis-api/issues/861)) ([#932](https://github.com/italofelipe/auraxis-api/issues/932)) ([d129587](https://github.com/italofelipe/auraxis-api/commit/d129587bfb4eb8993b9c72a7295005f0668fd377))
* **lgpd:** complete account deletion flow — [#885](https://github.com/italofelipe/auraxis-api/issues/885) ([#930](https://github.com/italofelipe/auraxis-api/issues/930)) ([e8f5ce8](https://github.com/italofelipe/auraxis-api/commit/e8f5ce8b8ec6d8ef1e16d720d672724dc4caacc3))


### Bug Fixes

* **auth:** SEC-GAP-01 — httpOnly refresh cookie (split-token) ([#944](https://github.com/italofelipe/auraxis-api/issues/944)) ([4638681](https://github.com/italofelipe/auraxis-api/commit/463868143cf0332af52eb1508eac73b95f90c559))
* **cors:** add pilot origin and preflight smoke test ([#933](https://github.com/italofelipe/auraxis-api/issues/933)) ([16d9b02](https://github.com/italofelipe/auraxis-api/commit/16d9b020490d60d99d41d12a4dd690778560975e))
* **hardening:** HARD-01 Dockerfile HEALTHCHECK + HARD-04 N+1 portfolio history ([#927](https://github.com/italofelipe/auraxis-api/issues/927)) ([5a17a07](https://github.com/italofelipe/auraxis-api/commit/5a17a075429e206a6b0ab6a4d3c73d4dab3c9cb3))
* **newman:** repair full suite regressions — v2 token read and accessToken variable ([#935](https://github.com/italofelipe/auraxis-api/issues/935)) ([5b3c848](https://github.com/italofelipe/auraxis-api/commit/5b3c8485459434dac9bf4237f620ca7642b5cbab))

## [1.21.0](https://github.com/italofelipe/auraxis-api/compare/v1.20.0...v1.21.0) (2026-04-07)


### Features

* **billing:** align prices, add trial-expiry CLI, document billing env vars ([#914](https://github.com/italofelipe/auraxis-api/issues/914)) ([04909d0](https://github.com/italofelipe/auraxis-api/commit/04909d0a76cafca35e3f1c5d6fdd8d9efbd11360))
* **billing:** H-PROD-01 — price alignment, trial CLI, env docs, Asaas fallback ([#915](https://github.com/italofelipe/auraxis-api/issues/915)) ([8dd27f7](https://github.com/italofelipe/auraxis-api/commit/8dd27f700f1f202a719bfdb935eeef37efd29d7f))


### Bug Fixes

* **deploy:** Phase 1 skips missing db service + proactive disk prune ([#911](https://github.com/italofelipe/auraxis-api/issues/911)) ([8f1e59d](https://github.com/italofelipe/auraxis-api/commit/8f1e59d04a00c30f526b5bda8ad37948c822b6e3))

## [1.20.0](https://github.com/italofelipe/auraxis-api/compare/v1.19.0...v1.20.0) (2026-04-06)


### Features

* **cache:** entitlement + JWT revocation Redis cache [HARD-05, B22] ([#906](https://github.com/italofelipe/auraxis-api/issues/906)) ([6b96ca5](https://github.com/italofelipe/auraxis-api/commit/6b96ca53aeb34cceb3f6c7feff8927709197a426))


### Bug Fixes

* **infra:** nginx security headers + gunicorn hardening [HARD-02, HARD-03] ([#905](https://github.com/italofelipe/auraxis-api/issues/905)) ([f4282f8](https://github.com/italofelipe/auraxis-api/commit/f4282f8980ff53c36c6d07bd74035ba82af06e2d))

## [1.19.0](https://github.com/italofelipe/auraxis-api/compare/v1.18.0...v1.19.0) (2026-04-06)


### Features

* **budget:** Budget model + CRUD endpoints + spent calculation ([#898](https://github.com/italofelipe/auraxis-api/issues/898)) ([39ce8f5](https://github.com/italofelipe/auraxis-api/commit/39ce8f53bf05518cd435c8d8ee36c718b3d42251))
* **user:** LGPD-compliant account deletion (DELETE /user/me) ([#897](https://github.com/italofelipe/auraxis-api/issues/897)) ([a05304c](https://github.com/italofelipe/auraxis-api/commit/a05304c94635c9a7d3c8fc47cc04bd0e244f97a8))

## [1.18.0](https://github.com/italofelipe/auraxis-api/compare/v1.17.0...v1.18.0) (2026-04-05)


### Features

* **bloco2:** dashboard trends + enriched Account/CreditCard + Tags color/icon ([#895](https://github.com/italofelipe/auraxis-api/issues/895)) ([dc276fe](https://github.com/italofelipe/auraxis-api/commit/dc276fe7041eed12433681aebd8e4ea3507a7fe0))


### Bug Fixes

* **security:** enforce admin role on feature flags admin endpoints ([#891](https://github.com/italofelipe/auraxis-api/issues/891)) ([1efedbe](https://github.com/italofelipe/auraxis-api/commit/1efedbe2dc1c5db503d57dba1f73a3cc4e8bce68))
* **transactions:** PATCH accepts null for description, end_date and start_date ([#892](https://github.com/italofelipe/auraxis-api/issues/892)) ([36180b5](https://github.com/italofelipe/auraxis-api/commit/36180b5d4e7226b70ef737aee3602dbe90dd50c1)), closes [#846](https://github.com/italofelipe/auraxis-api/issues/846)
* **transactions:** PATCH null fields for all contract versions (v1/v2/v3) ([#896](https://github.com/italofelipe/auraxis-api/issues/896)) ([ba594ce](https://github.com/italofelipe/auraxis-api/commit/ba594ce4c8453e04f41331bc8ef5df3cf0afa2cf))

## [1.17.0](https://github.com/italofelipe/auraxis-api/compare/v1.16.1...v1.17.0) (2026-04-05)


### Features

* **ci:** H-CI-01 — staging deploy workflow + post-deploy smoke test ([#880](https://github.com/italofelipe/auraxis-api/issues/880)) ([97db2dd](https://github.com/italofelipe/auraxis-api/commit/97db2dd4cd3cbfe0aa0c206ad894fcac21a95247)), closes [#864](https://github.com/italofelipe/auraxis-api/issues/864)
* **flags:** INFRA-FF — Redis-backed feature flags with canary % deploy ([#882](https://github.com/italofelipe/auraxis-api/issues/882)) ([8a3e8b8](https://github.com/italofelipe/auraxis-api/commit/8a3e8b8c2e46d1396d887d0d9c1d2bb2e6abfd97))

## [1.16.1](https://github.com/italofelipe/auraxis-api/compare/v1.16.0...v1.16.1) (2026-04-05)


### Performance Improvements

* **brapi:** add circuit breaker + SQLAlchemy connection pool tuning ([#877](https://github.com/italofelipe/auraxis-api/issues/877)) ([0b600cd](https://github.com/italofelipe/auraxis-api/commit/0b600cd9c89b1ef9631fe24745d45c90004b228d))

## [1.16.0](https://github.com/italofelipe/auraxis-api/compare/v1.15.0...v1.16.0) (2026-04-05)


### Features

* **cache:** CACHE-01 — Redis caching layer for dashboard, BRAPI & portfolio queries ([#875](https://github.com/italofelipe/auraxis-api/issues/875)) ([e54a362](https://github.com/italofelipe/auraxis-api/commit/e54a3628139940929187f451a9e6f5c8d58bdb1a))

## [1.15.0](https://github.com/italofelipe/auraxis-api/compare/v1.14.1...v1.15.0) (2026-04-04)


### Features

* **billing:** Asaas checkout + webhook + trial period + entitlement activation ([#860](https://github.com/italofelipe/auraxis-api/issues/860)) ([#869](https://github.com/italofelipe/auraxis-api/issues/869)) ([c999594](https://github.com/italofelipe/auraxis-api/commit/c999594f642756ee0414d1539e90529dcc796da4))

## [1.14.1](https://github.com/italofelipe/auraxis-api/compare/v1.14.0...v1.14.1) (2026-04-04)


### Bug Fixes

* **deps:** pin prometheus-client to 0.24.1 ([#865](https://github.com/italofelipe/auraxis-api/issues/865)) ([19b43d6](https://github.com/italofelipe/auraxis-api/commit/19b43d6e09362ab660e3ba140fc730d3a5445f5c))

## [1.14.0](https://github.com/italofelipe/auraxis-api/compare/v1.13.1...v1.14.0) (2026-04-03)


### Features

* **api:** /readiness endpoint, disable GraphQL introspection in prod, add DB indexes (B19/B20/B21) ([#851](https://github.com/italofelipe/auraxis-api/issues/851)) ([1dce441](https://github.com/italofelipe/auraxis-api/commit/1dce441fcf9e986afe214bb5b39ee6f6b180e868))
* **auth:** add POST /auth/refresh with token rotation (B18) ([#830](https://github.com/italofelipe/auraxis-api/issues/830)) ([0f07dfe](https://github.com/italofelipe/auraxis-api/commit/0f07dfe3e1adad6b00e02fb9277e65cc667f7f9e))
* **auth:** Redis cache for JWT revocation check — eliminate DB hit per request (B22) ([#847](https://github.com/italofelipe/auraxis-api/issues/847)) ([0056b27](https://github.com/italofelipe/auraxis-api/commit/0056b276d8567e3c977b0e5c22d29f09363196b9))
* **deploy:** rolling web-only restart preserves db/redis across deploys ([#845](https://github.com/italofelipe/auraxis-api/issues/845)) ([2ebda00](https://github.com/italofelipe/auraxis-api/commit/2ebda00e4128f99663755b64b7d1bf439ed1ae66))
* **observability:** Prometheus metrics + request_id correlation (API23) ([#850](https://github.com/italofelipe/auraxis-api/issues/850)) ([ba9a5d6](https://github.com/italofelipe/auraxis-api/commit/ba9a5d60a29c64b9170bed5f9ede96e28d3c263f))


### Bug Fixes

* **recurrence:** [[#701](https://github.com/italofelipe/auraxis-api/issues/701)] add error handling and non-zero exit on failure ([#848](https://github.com/italofelipe/auraxis-api/issues/848)) ([7a960c5](https://github.com/italofelipe/auraxis-api/commit/7a960c5838e060d4df5400ec13471779b4187734))
* **transactions:** allow null for optional fields in PATCH schema (closes [#846](https://github.com/italofelipe/auraxis-api/issues/846)) ([#849](https://github.com/italofelipe/auraxis-api/issues/849)) ([040adc4](https://github.com/italofelipe/auraxis-api/commit/040adc4360f0b1cb3f83e8f2c0aa4eb1a3013dd5))

## [1.13.1](https://github.com/italofelipe/auraxis-api/compare/v1.13.0...v1.13.1) (2026-04-01)


### Bug Fixes

* **deploy:** disk/swap pre-flight to prevent OOM and disk-full incidents ([#822](https://github.com/italofelipe/auraxis-api/issues/822)) ([c2e9f34](https://github.com/italofelipe/auraxis-api/commit/c2e9f34ea5269cc12e5c8e7c26407a7e91a8e45b))
* **sentry:** before_send quota guard + SENTRY_ERROR_RATE ([#823](https://github.com/italofelipe/auraxis-api/issues/823)) ([1fd3329](https://github.com/italofelipe/auraxis-api/commit/1fd33290381db9f9bf74b10c27a2e3bf3f93fb56))

## [1.13.0](https://github.com/italofelipe/auraxis-api/compare/v1.12.0...v1.13.0) (2026-03-31)


### Features

* **email:** branded transactional email templates + Route53 deliverability fix ([#818](https://github.com/italofelipe/auraxis-api/issues/818)) ([fe95677](https://github.com/italofelipe/auraxis-api/commit/fe9567740c2278fb969dec84b303e4b233c2c3ed))


### Bug Fixes

* **auth:** protect /auth/email/resend with JWT ([#816](https://github.com/italofelipe/auraxis-api/issues/816)) ([1788eaa](https://github.com/italofelipe/auraxis-api/commit/1788eaa23fcea71703d5743b6ef555c5189ac920))

## [1.12.0](https://github.com/italofelipe/auraxis-api/compare/v1.11.0...v1.12.0) (2026-03-30)


### Features

* **api:** add email confirmation foundation ([#807](https://github.com/italofelipe/auraxis-api/issues/807)) ([908d10e](https://github.com/italofelipe/auraxis-api/commit/908d10e488b7f5124f4c2e88da6de8f353f4f0cb))
* **api:** add observability export surface ([#808](https://github.com/italofelipe/auraxis-api/issues/808)) ([5e1c0ff](https://github.com/italofelipe/auraxis-api/commit/5e1c0ff27c69fcf01d888003258cf54c5e5f442d))
* **auth:** add Cloudflare Turnstile CAPTCHA verification to register and login ([#814](https://github.com/italofelipe/auraxis-api/issues/814)) ([8ddd5ec](https://github.com/italofelipe/auraxis-api/commit/8ddd5ec09339eadff4b1c101d8b6bc87508d10c3))
* **shared-entries:** enrich serializer with transaction + invitation data [B2] ([#805](https://github.com/italofelipe/auraxis-api/issues/805)) ([9fde2f3](https://github.com/italofelipe/auraxis-api/commit/9fde2f3de3aa9850d5533c0cc891ec57d409b48b))


### Bug Fixes

* **ci:** replace indented heredoc with jq in deploy summary; add SSM retry ([#809](https://github.com/italofelipe/auraxis-api/issues/809)) ([2ffb66c](https://github.com/italofelipe/auraxis-api/commit/2ffb66c2d196f7c4b74c9cddeeb2e3e8c14a0556))

## [1.11.0](https://github.com/italofelipe/auraxis-api/compare/v1.10.0...v1.11.0) (2026-03-29)


### Features

* **api:** F1-F3 — tags, accounts, credit-cards REST endpoints ([#797](https://github.com/italofelipe/auraxis-api/issues/797)) ([5ec620f](https://github.com/italofelipe/auraxis-api/commit/5ec620f4bc254ba3143c17b0edd9eca0e139984e))
* **api:** integrate Asaas hosted checkout and webhook sync ([#800](https://github.com/italofelipe/auraxis-api/issues/800)) ([602b941](https://github.com/italofelipe/auraxis-api/commit/602b94191cded563f5efda623314c5d13fa71d9e))
* **api:** publish billing plan catalog ([#799](https://github.com/italofelipe/auraxis-api/issues/799)) ([bdde07a](https://github.com/italofelipe/auraxis-api/commit/bdde07a8876c49e40801d8368526bcb39cd388ba))
* **seeds:** G5 — local development seed script with demo data ([#798](https://github.com/italofelipe/auraxis-api/issues/798)) ([e066305](https://github.com/italofelipe/auraxis-api/commit/e066305df6676df67b40d15e11561d2117497654))


### Bug Fixes

* call .scalar_subquery() on the select() before passing to .in_(). ([49f104f](https://github.com/italofelipe/auraxis-api/commit/49f104f651b17016b76cd89a7b7e7e9389eeafa8))
* **shared-entries:** add .scalar_subquery() to fix 500 on GET /with-me ([#802](https://github.com/italofelipe/auraxis-api/issues/802)) ([49f104f](https://github.com/italofelipe/auraxis-api/commit/49f104f651b17016b76cd89a7b7e7e9389eeafa8))

## [1.10.0](https://github.com/italofelipe/auraxis-api/compare/v1.9.0...v1.10.0) (2026-03-29)


### Features

* **api-18-3:** clarify graphql dashboard ownership ([#786](https://github.com/italofelipe/auraxis-api/issues/786)) ([81eb42c](https://github.com/italofelipe/auraxis-api/commit/81eb42cf26b25c30003c79136de4487b5eb28d0b))
* **ci:** add canonical stack bootstrap ([#789](https://github.com/italofelipe/auraxis-api/issues/789)) ([c13e934](https://github.com/italofelipe/auraxis-api/commit/c13e93409c09436f33509483babacb12d002d18b))
* **ci:** add continuous suite canary ([#792](https://github.com/italofelipe/auraxis-api/issues/792)) ([d0036cb](https://github.com/italofelipe/auraxis-api/commit/d0036cb0dfee6f2acec7b6fb864f5dd22caf7808))
* **ci:** align local suite bootstrap with ci ([#791](https://github.com/italofelipe/auraxis-api/issues/791)) ([b52f3df](https://github.com/italofelipe/auraxis-api/commit/b52f3df3c0a32e7db5b7f883cf36c20289fdb5c7))


### Performance Improvements

* **api-19-1:** prebuild web image for release gates ([#785](https://github.com/italofelipe/auraxis-api/issues/785)) ([aaefc52](https://github.com/italofelipe/auraxis-api/commit/aaefc529066a24ce04211b811215b0ea8350b8ab))

## [1.9.0](https://github.com/italofelipe/auraxis-api/compare/v1.8.0...v1.9.0) (2026-03-28)


### Features

* **auth:** harden canonical login identity ([#762](https://github.com/italofelipe/auraxis-api/issues/762)) ([02d0832](https://github.com/italofelipe/auraxis-api/commit/02d08328473c4c8cd8be8bb7b5afeca4f8df14cc))
* **dashboard:** canonicalize graphql overview ownership ([#767](https://github.com/italofelipe/auraxis-api/issues/767)) ([779d53b](https://github.com/italofelipe/auraxis-api/commit/779d53b07087d9beda7ca0dd58243d734410d64a))
* **goals:** normalize update and simulation semantics ([#765](https://github.com/italofelipe/auraxis-api/issues/765)) ([2da383a](https://github.com/italofelipe/auraxis-api/commit/2da383a0995fb9e50ad80b0a007645d26f8037bc))
* **graphql:** align transactions with canonical filters ([#766](https://github.com/italofelipe/auraxis-api/issues/766)) ([d5fbcf8](https://github.com/italofelipe/auraxis-api/commit/d5fbcf844b98159231177210d0f3d2ba20eb8d18))
* **transactions:** finalize mvp1 rest stabilization ([#750](https://github.com/italofelipe/auraxis-api/issues/750)) ([e7cbb6f](https://github.com/italofelipe/auraxis-api/commit/e7cbb6fbb8a46838997b9943da0101ce79533304))
* **wallet:** normalize canonical detail and update semantics ([#764](https://github.com/italofelipe/auraxis-api/issues/764)) ([6339481](https://github.com/italofelipe/auraxis-api/commit/63394815ca4e0e065fc620b8a661cbce99cec67c))


### Performance Improvements

* **transactions:** simplify hot query paths ([#778](https://github.com/italofelipe/auraxis-api/issues/778)) ([ade4404](https://github.com/italofelipe/auraxis-api/commit/ade4404a4765f9b751800f0dfd90676efe5e0e03))
* **user:** optimize canonical me and bootstrap preview ([#763](https://github.com/italofelipe/auraxis-api/issues/763)) ([38632a4](https://github.com/italofelipe/auraxis-api/commit/38632a4ea5b39ad91f8a63716fd5ae75063d0fcf))

## [1.8.0](https://github.com/italofelipe/auraxis-api/compare/v1.7.0...v1.8.0) (2026-03-27)


### Features

* **transactions:** normalize update semantics and filters ([#749](https://github.com/italofelipe/auraxis-api/issues/749)) ([b3e5794](https://github.com/italofelipe/auraxis-api/commit/b3e5794feb50e1893d875a201029993a36550232))
* **transactions:** publish canonical collection and detail reads ([#746](https://github.com/italofelipe/auraxis-api/issues/746)) ([d79e81f](https://github.com/italofelipe/auraxis-api/commit/d79e81f946e565f0f37cb56afcafd4327a7873ae))

## [1.7.0](https://github.com/italofelipe/auraxis-api/compare/v1.6.0...v1.7.0) (2026-03-27)


### Features

* **gov:** add pr traceability checks ([#722](https://github.com/italofelipe/auraxis-api/issues/722)) ([cb7896e](https://github.com/italofelipe/auraxis-api/commit/cb7896e9bb492fa8a759426eae34893f9ec372c5))
* **j2:** complete bank statement import flow ([#720](https://github.com/italofelipe/auraxis-api/issues/720)) ([6ffaab3](https://github.com/italofelipe/auraxis-api/commit/6ffaab3fcb81b21db0c7663536b38b03a4110aff))
* **obs:** enrich lightweight request correlation ([#726](https://github.com/italofelipe/auraxis-api/issues/726)) ([458c595](https://github.com/italofelipe/auraxis-api/commit/458c59582b784e71aa1ef0427d7607b306708ed5))
* **perf:** add latency budget governance gate ([#724](https://github.com/italofelipe/auraxis-api/issues/724)) ([21ad839](https://github.com/italofelipe/auraxis-api/commit/21ad839cf937334e0dc5a0ad58cbf391981aba3f))
* **user:** add explicit bootstrap endpoint ([#738](https://github.com/italofelipe/auraxis-api/issues/738)) ([5fa4b39](https://github.com/italofelipe/auraxis-api/commit/5fa4b39262d75d2cd6f79822883d5a12a9911dd5))
* **user:** publish canonical me contract ([#737](https://github.com/italofelipe/auraxis-api/issues/737)) ([2fc0c21](https://github.com/italofelipe/auraxis-api/commit/2fc0c2133e9cbdf3f5098e9553d8885da84dcbe9))

## [1.6.0](https://github.com/italofelipe/auraxis-api/compare/v1.5.0...v1.6.0) (2026-03-26)


### Features

* **j2:** add bank import transaction foundation ([#716](https://github.com/italofelipe/auraxis-api/issues/716)) ([7106379](https://github.com/italofelipe/auraxis-api/commit/71063799d7c04a80d76b7f1f2e76c63418d3cd95))
* **j2:** add ofx and nubank parsers ([#717](https://github.com/italofelipe/auraxis-api/issues/717)) ([7c28d08](https://github.com/italofelipe/auraxis-api/commit/7c28d087202468da2f83c9bbc601ca865e6b0849))


### Bug Fixes

* **ops:** run recurrence job via ssm ([#714](https://github.com/italofelipe/auraxis-api/issues/714)) ([ee26ffe](https://github.com/italofelipe/auraxis-api/commit/ee26ffe2ab47f1405922bd8f9ddee64e09d923f8))

## [1.5.0](https://github.com/italofelipe/auraxis-api/compare/v1.4.0...v1.5.0) (2026-03-26)


### Features

* **api:** unify rest errors and add latency baseline ([#700](https://github.com/italofelipe/auraxis-api/issues/700)) ([f3c807d](https://github.com/italofelipe/auraxis-api/commit/f3c807d8ea21957ce984fac022bdf0d4f263e115))
* **observability:** add low-cost api ops baseline ([#698](https://github.com/italofelipe/auraxis-api/issues/698)) ([062a4af](https://github.com/italofelipe/auraxis-api/commit/062a4af2361cde185972d9542bb498a1d078601a))


### Bug Fixes

* **api:** bootstrap operational scripts from repo root ([#702](https://github.com/italofelipe/auraxis-api/issues/702)) ([15303e5](https://github.com/italofelipe/auraxis-api/commit/15303e531f756e1391e674b61e14920bcaa712a0))
* isolate internal runtime from http middleware ([#706](https://github.com/italofelipe/auraxis-api/issues/706)) ([dba5d4d](https://github.com/italofelipe/auraxis-api/commit/dba5d4d08dc98409898c0df170537d03af90fefa))

## [1.4.0](https://github.com/italofelipe/auraxis-api/compare/v1.3.0...v1.4.0) (2026-03-22)


### Features

* **postman:** audit remaining route parity gaps ([#684](https://github.com/italofelipe/auraxis-api/issues/684)) ([e35dbe6](https://github.com/italofelipe/auraxis-api/commit/e35dbe62f4c8e26eb76cc751bb89e8c79d1199c9))
* **postman:** expand canonical e2e parity coverage ([#682](https://github.com/italofelipe/auraxis-api/issues/682)) ([45d6dc2](https://github.com/italofelipe/auraxis-api/commit/45d6dc2802fad8a869c81e8ca25cf99c326b049c))
* **postman:** isolate privileged integration profile ([#683](https://github.com/italofelipe/auraxis-api/issues/683)) ([dfc6b5d](https://github.com/italofelipe/auraxis-api/commit/dfc6b5d062971ee1753793794f2f5514b31c8bee))
* **test:** add smoke and full postman profiles ([#669](https://github.com/italofelipe/auraxis-api/issues/669)) ([dd19e82](https://github.com/italofelipe/auraxis-api/commit/dd19e82dea39ff9a75ca84f8c19cd3576ad40ae4))


### Bug Fixes

* **auth:** harden webhook boundary and remove legacy jwt path ([#679](https://github.com/italofelipe/auraxis-api/issues/679)) ([774aab9](https://github.com/italofelipe/auraxis-api/commit/774aab991528a880610a9b4b4bd5f846b763417d))
* **ci:** add dedicated newman integration gate ([#681](https://github.com/italofelipe/auraxis-api/issues/681)) ([866cd48](https://github.com/italofelipe/auraxis-api/commit/866cd482cfd34c74ddb604107025006edf19ad76))
* **ops:** harden recurrence incidents and rate limit fallback ([#680](https://github.com/italofelipe/auraxis-api/issues/680)) ([784ab2c](https://github.com/italofelipe/auraxis-api/commit/784ab2cf88ac0ad1e8eec7673218845ec78108cf))
* **ops:** stabilize newman full runtime drift ([#686](https://github.com/italofelipe/auraxis-api/issues/686)) ([9441a52](https://github.com/italofelipe/auraxis-api/commit/9441a5215a9ea2bae6699c6f2c73808a54e12d0e))

## [1.3.0](https://github.com/italofelipe/auraxis-api/compare/v1.2.0...v1.3.0) (2026-03-22)


### Features

* **infra:** add alb edge mode for api runtime ([#658](https://github.com/italofelipe/auraxis-api/issues/658)) ([d0cb02d](https://github.com/italofelipe/auraxis-api/commit/d0cb02dd46598ad96ba89a243671ec6a832978e2))
* **ops:** automate dev host recovery baseline ([#664](https://github.com/italofelipe/auraxis-api/issues/664)) ([7663ee1](https://github.com/italofelipe/auraxis-api/commit/7663ee1ff27e607b7138271cf64164239d3cf197))
* **ops:** improve deploy and sonar diagnostics ([#665](https://github.com/italofelipe/auraxis-api/issues/665)) ([9588e47](https://github.com/italofelipe/auraxis-api/commit/9588e475ab86b9500b2db8763d9f3c7351e93e8c))
* **testing:** establish canonical postman e2e suite ([#668](https://github.com/italofelipe/auraxis-api/issues/668)) ([5aebfe2](https://github.com/italofelipe/auraxis-api/commit/5aebfe24000f04bbf0a8fb6eb014c330d1977834))


### Bug Fixes

* **deploy:** add dual edge mode for alb cutover ([#662](https://github.com/italofelipe/auraxis-api/issues/662)) ([f53d416](https://github.com/italofelipe/auraxis-api/commit/f53d416636e5cc1b39985e4fa92d753c86e7ec4a))

## [1.2.0](https://github.com/italofelipe/auraxis-api/compare/v1.1.0...v1.2.0) (2026-03-21)


### Features

* add installment vs cash simulation contract ([#647](https://github.com/italofelipe/auraxis-api/issues/647)) ([02019f5](https://github.com/italofelipe/auraxis-api/commit/02019f549f3ef86b36a60e62cd8adab935ed2ef9))


### Bug Fixes

* **ci:** let release please trigger release pr checks ([#643](https://github.com/italofelipe/auraxis-api/issues/643)) ([f05f809](https://github.com/italofelipe/auraxis-api/commit/f05f80978f5048f44d5f5d2d40d90934206fc25f))

## [1.1.0](https://github.com/italofelipe/auraxis-api/compare/v1.0.0...v1.1.0) (2026-03-19)


### Features

* **alerts:** J11-2 — alert dispatch matrix and scheduler endpoints ([#627](https://github.com/italofelipe/auraxis-api/issues/627)) ([f6e7ac0](https://github.com/italofelipe/auraxis-api/commit/f6e7ac02b0c6aaeefef25e0d630c3a3d0c8ebb52))
* **infra:** integrate Sentry SDK with Flask for error tracking and performance monitoring ([#625](https://github.com/italofelipe/auraxis-api/issues/625)) ([48a7b36](https://github.com/italofelipe/auraxis-api/commit/48a7b36a2f6c68d4cef212943f6d28a99ac217cb)), closes [#616](https://github.com/italofelipe/auraxis-api/issues/616)
* **infra:** smoke test automatizado pós-deploy via Newman (DoD [#617](https://github.com/italofelipe/auraxis-api/issues/617)) ([#632](https://github.com/italofelipe/auraxis-api/issues/632)) ([b22976b](https://github.com/italofelipe/auraxis-api/commit/b22976b2d11e35807c89641520022d143ff14056))
* **j12:** subscription state & entitlement enforcement ([#629](https://github.com/italofelipe/auraxis-api/issues/629)) ([c32b768](https://github.com/italofelipe/auraxis-api/commit/c32b76831205499a4e72cd6149af59872752356a))
* **j13:** shared entries, invitations and audit contract ([#630](https://github.com/italofelipe/auraxis-api/issues/630)) ([913a06a](https://github.com/italofelipe/auraxis-api/commit/913a06ac57607548a477dcb0697da36079ce31f3))
* **j14:** generic CSV ingestion and receivable/fiscal document endpoints ([#631](https://github.com/italofelipe/auraxis-api/issues/631)) ([1cedb62](https://github.com/italofelipe/auraxis-api/commit/1cedb6258f4e1fb510c177ea2be13fc4e250289e))
* **j7:** simulation persistence, goals PATCH and entitlement endpoints ([#628](https://github.com/italofelipe/auraxis-api/issues/628)) ([1334488](https://github.com/italofelipe/auraxis-api/commit/133448851f80c4d9e813b0b82820f8a07fec1c13))
* **j9:** billing provider adapter and subscription state endpoints ([#626](https://github.com/italofelipe/auraxis-api/issues/626)) ([aaa867c](https://github.com/italofelipe/auraxis-api/commit/aaa867c2e1c4125aee366d1c531090fde22068c8))
* **models+migrations:** complete J-task foundation — Entitlement model, migration, and unit tests ([#624](https://github.com/italofelipe/auraxis-api/issues/624)) ([1697757](https://github.com/italofelipe/auraxis-api/commit/16977575a0b811459c1774e2ef12034c4a5f7406))
* **user:** implement investor profile questionnaire ([#588](https://github.com/italofelipe/auraxis-api/issues/588)) ([130ddae](https://github.com/italofelipe/auraxis-api/commit/130ddaeb3520a9f76084aa4cddbda2ca6901b77d))
* **user:** implement salary increase simulation endpoint ([#603](https://github.com/italofelipe/auraxis-api/issues/603)) ([a48bfb2](https://github.com/italofelipe/auraxis-api/commit/a48bfb22cf3f431f466fdd26c6a0f9978a15de54))

## Changelog

All notable changes to this project will be documented in this file.

This file is the baseline for automated release management via Release Please.
Subsequent entries should be generated from release automation.

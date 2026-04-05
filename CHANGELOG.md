# Changelog

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

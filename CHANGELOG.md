# Changelog

## [1.34.0](https://github.com/italofelipe/auraxis-api/compare/v1.33.0...v1.34.0) (2026-05-03)


### Features

* **audit:** record entity-delete audit events for goals, wallet, subscriptions ([#1160](https://github.com/italofelipe/auraxis-api/issues/1160)) ([ef89098](https://github.com/italofelipe/auraxis-api/commit/ef890984cf9d72ff43c39bf5189a20e277f0b113))
* **entitlements:** add focus_mode to premium plan ([#1117](https://github.com/italofelipe/auraxis-api/issues/1117)) ([893820f](https://github.com/italofelipe/auraxis-api/commit/893820fa0a6a44b5fc7fb22098bc24fff71d6e78))
* **simulations:** allowlist aposentadoria + desconto-markup in TOOLS_REGISTRY ([#1132](https://github.com/italofelipe/auraxis-api/issues/1132)) ([3cb8147](https://github.com/italofelipe/auraxis-api/commit/3cb8147408ac63c1bbf0efa9f3e6e19347a8df24))
* **simulations:** canonical generic /simulations endpoint ([#1128](https://github.com/italofelipe/auraxis-api/issues/1128)) ([#1130](https://github.com/italofelipe/auraxis-api/issues/1130)) ([2124a9e](https://github.com/italofelipe/auraxis-api/commit/2124a9e270561be906e1a78b07e2c93c59df541e))


### Bug Fixes

* **graphql:** replace Float with DecimalScalar on monetary fields, paginate tickers ([#1158](https://github.com/italofelipe/auraxis-api/issues/1158)) ([e6dab69](https://github.com/italofelipe/auraxis-api/commit/e6dab693bcff0ae959d88696e76c252f98a612bb))
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

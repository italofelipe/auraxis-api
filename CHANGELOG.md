# Changelog

## [1.3.0](https://github.com/italofelipe/auraxis-api/compare/v1.2.0...v1.3.0) (2026-03-22)


### Features

* **infra:** add alb edge mode for api runtime ([#658](https://github.com/italofelipe/auraxis-api/issues/658)) ([d0cb02d](https://github.com/italofelipe/auraxis-api/commit/d0cb02dd46598ad96ba89a243671ec6a832978e2))


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

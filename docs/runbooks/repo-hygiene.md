# Repo hygiene — duplicate-suffix files (`foo 2.py`)

## Sintoma

`scripts/repo_hygiene_check.py` falha em CI ou no pre-commit com:

```
[repo-hygiene-check] suspicious duplicate-suffix files detected:
- app/controllers/auth/login_resource 2.py
- ...
```

ou seu pre-commit local emite:

```
BLOQUEADO: arquivos duplicados macOS detectados antes do commit:
  app/controllers/auth/login_resource 2.py
```

## Causa raiz

macOS Finder / iCloud Drive sync / Time Machine criam cópias automáticas
quando dois processos escrevem no mesmo arquivo (acontece com agentes de
IA rodando em paralelo via worktrees / symlinks). O nome segue o padrão
`<name> <digit>.<ext>` ou `<name> <digit>` (diretórios).

Estes nunca devem ser commitados. Pior: como Python pode resolver o
módulo errado em runtimes que normalizam separadores, podem **silenciar
proteções de segurança** (e.g., versões antigas de
`refresh_token_resource 2.py` sem replay-guard).

## Remediação

### Listar (sem deletar)

```bash
bash scripts/clean-duplicate-files.sh --dry-run
```

Saída enumera arquivos e diretórios duplicados.

### Deletar

```bash
bash scripts/clean-duplicate-files.sh
```

O script **recusa deletar arquivos git-tracked** — esses precisam de
`git rm` em commit deliberado, não janitor automático.

Diretórios duplicados são removidos primeiro, arquivos depois. Cobertura:
`*.py`, `*.md`, `*.json`, `*.graphql`, `*.yml`, `*.toml`, qualquer
extensão alfanumérica.

## Prevenção

- **Pre-commit** (`scripts/no_duplicate_files_check.py`) bloqueia
  arquivos duplicados ao tentar `git commit`.
- **CI** (`scripts/repo_hygiene_check.py` em `.github/workflows/ci.yml`)
  varre todo o working tree em cada PR e falha se encontrar.
- **Local periódico**: rodar `bash scripts/clean-duplicate-files.sh`
  após sessão longa de IA, antes de `git push`.

## Diretórios excluídos do scan

`./.git`, `./.venv`, `./venv`, `./.mypy_cache`, `./.pytest_cache`,
`./.ruff_cache`, `__pycache__`, `./node_modules`, `./_worktrees`,
`./coverage`, `./htmlcov`, `./dist`, `./build`. Caches são reescritos
naturalmente — não vale gastar tempo limpando.

## Histórico

- 2026-05-01 — primeira limpeza retroativa: 26 duplicates removidos
  (auth/session/advisory paths críticos). Script `clean-duplicate-files.sh`
  portado de `auraxis-app` (PR #1136). Issue #1133.

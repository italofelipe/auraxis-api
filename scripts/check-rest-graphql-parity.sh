#!/usr/bin/env bash
# check-rest-graphql-parity.sh
#
# Gate ADVISORY (não bloqueante) da regra "toda feature expõe REST e GraphQL"
# (ADR 0002 / 0008). Emite o INVENTÁRIO dos dois lados para revisão manual de
# paridade — não tenta casar nomes automaticamente (REST usa snake_case,
# GraphQL usa camelCase/tipos, então matching heurístico gera falso-positivo).
#
# Sempre sai 0 (advisory) até a paridade atingir o alvo e o gate ser promovido
# a bloqueante com um matcher confiável (ver ADR 0008 "follow-up").
#
# Uso: bash scripts/check-rest-graphql-parity.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Paridade REST ↔ GraphQL — inventário (advisory, ADR 0008) =="
echo ""
echo "-- Controllers REST (app/controllers) --"
find "$ROOT/app/controllers" -maxdepth 1 \( -name '*_controller.py' -o -type d \) 2>/dev/null \
  | sed -E 's#.*/##; s/_controller\.py$//' \
  | grep -vE '^(__pycache__|__init__\.py|controllers)$' \
  | sort -u | sed 's/^/  REST  /'

echo ""
echo "-- Resolvers GraphQL (app/graphql/queries + mutations) --"
find "$ROOT/app/graphql/queries" "$ROOT/app/graphql/mutations" -name '*.py' 2>/dev/null \
  | sed -E 's#.*/##; s/\.py$//' \
  | grep -vE '^__init__$' \
  | sort -u | sed 's/^/  GQL   /'

echo ""
echo "[parity] Revise manualmente: toda query de dados deve existir em REST e GraphQL"
echo "         (ADR 0002/0008). Advisory — não bloqueia o CI."
exit 0

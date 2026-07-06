#!/bin/bash
# SessionStart hook — prépare l'environnement des sessions Claude Code on the web
# pour que les portes de contrôle (npm run build, py_compile) soient exécutables.
# Idempotent : npm install ne refait rien si node_modules est déjà à jour
# (l'état du conteneur est mis en cache après le hook).
set -euo pipefail

# Uniquement dans les sessions distantes (Claude Code on the web / routines).
# En local sur la machine d'Alex, ne rien faire.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR/frontend"
npm install --no-audit --no-fund
echo "SessionStart: dépendances frontend installées."

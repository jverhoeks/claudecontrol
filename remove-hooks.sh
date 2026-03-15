#!/usr/bin/env bash
set -euo pipefail

SETTINGS_FILE="$HOME/.claude/settings.json"

echo ""
echo "  🛡️  Claude Control — Remove Hooks"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -f "$SETTINGS_FILE" ]; then
    echo "  ℹ️  No settings file found at $SETTINGS_FILE — nothing to remove."
    exit 0
fi

python3 -c "
import json

with open('$SETTINGS_FILE') as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
removed = []

for hook_name in ['PreToolUse', 'PermissionRequest', 'Stop']:
    if hook_name in hooks:
        # Remove only Claude Control hooks (matching localhost:8932)
        original = hooks[hook_name]
        filtered = [
            entry for entry in original
            if not any(
                h.get('url', '').startswith('http://localhost:8932/')
                for h in entry.get('hooks', [])
            )
        ]
        if len(filtered) < len(original):
            removed.append(hook_name)
        if filtered:
            hooks[hook_name] = filtered
        else:
            del hooks[hook_name]

if not hooks:
    settings.pop('hooks', None)
else:
    settings['hooks'] = hooks

with open('$SETTINGS_FILE', 'w') as f:
    json.dump(settings, f, indent=2)

for name in removed:
    print(f'  ✅ Removed {name} hook')

if not removed:
    print('  ℹ️  No Claude Control hooks found.')
"

echo ""
echo "  Done. Claude Code sessions will no longer route through governance."
echo ""

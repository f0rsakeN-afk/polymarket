import json
import sys

# Must match the call order in discord-notifications.yml:
#   send_discord.py "<branch>" "<commit_msg>" "<author>" "<files>" "<sha>" "<timestamp>"
branch = sys.argv[1]
commit_msg = sys.argv[2]
author = sys.argv[3]
files_changed = sys.argv[4]
sha_short = sys.argv[5]
timestamp = sys.argv[6]

# Discord embed limits: title 256, description 4096, field value 1024 chars.
# The files list is wrapped in a ```diff fence (12 chars of overhead).
commit_msg = commit_msg[:500]
fence_overhead = len("```diff\n\n```")
max_files = 1024 - fence_overhead
if len(files_changed) > max_files:
    files_changed = files_changed[:max_files] + "\n…truncated"
if not files_changed.strip():
    files_changed = "(no files)"

payload = {
    'embeds': [{
        'title': f'Code Pushed to {branch}',
        'description': f'**{commit_msg}**',
        'color': 16747520,
        'fields': [
            {'name': 'Author', 'value': author, 'inline': True},
            {'name': 'Branch', 'value': branch, 'inline': True},
            {'name': 'Files Changed', 'value': f'```diff\n{files_changed}\n```'}
        ],
        'footer': {'text': f'sha: {sha_short}'},
        'timestamp': timestamp
    }]
}

with open('payload.json', 'w') as f:
    json.dump(payload, f)

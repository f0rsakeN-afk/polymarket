import json
import sys

author = sys.argv[1]
branch = sys.argv[2]
commit_msg = sys.argv[3]
files_changed = sys.argv[4]
sha_short = sys.argv[5]
timestamp = sys.argv[6]

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



# Utilities


python3 -c "
import requests
from requests.auth import HTTPBasicAuth
auth = HTTPBasicAuth('admin', 'Admin123')
base = 'http://localhost:8080/openmrs/ws/rest/v1'

usernames = ['dr.mokoena', 'mpho.dlamini', 'dr.tau', 'thabiso.nkosi']

# Find Provider role UUID
roles = requests.get(f'{base}/role', auth=auth).json()['results']
provider_role = next(r for r in roles if r['display'] == 'Provider')
print(f'Provider role UUID: {provider_role[\"uuid\"]}')

for username in usernames:
    # Find user
    r = requests.get(f'{base}/user', params={'q': username}, auth=auth)
    results = r.json().get('results', [])
    if not results:
        print(f'  NOT FOUND: {username}')
        continue
    user_uuid = results[0]['uuid']

    # Fetch full user to get current roles
    u = requests.get(f'{base}/user/{user_uuid}', params={'v': 'full'}, auth=auth).json()
    current_roles = u.get('roles', [])
    role_uuids = [r['uuid'] for r in current_roles]

    if provider_role['uuid'] in role_uuids:
        print(f'  {username}: already has Provider role')
        continue

    role_uuids.append(provider_role['uuid'])
    patch = requests.post(
        f'{base}/user/{user_uuid}',
        json={'roles': [{'uuid': uid} for uid in role_uuids]},
        auth=auth
    )
    print(f'  {username}: {patch.status_code} — Provider role added')
"

import requests
from requests.auth import HTTPBasicAuth
auth = HTTPBasicAuth('admin', 'Admin123')
base = 'http://localhost:8080/openmrs'

# Restart the radiologyapp module via admin API
r = requests.post(f'{base}/moduleServlet/webservices.rest/moduleManagement',
    data={'action': 'restart', 'moduleId': 'radiologyapp'},
    auth=auth)
print(r.status_code, r.text[:200])

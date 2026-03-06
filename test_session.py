import requests
import json
import time

url = "http://localhost:4575"
s = requests.Session()
# Get CSRF token
print("1. Testing login...")
r = s.get(f"{url}/login")
try:
    csrf = r.text.split('name="csrf_token" value="')[1].split('"')[0]
    r = s.post(f"{url}/login", data={"csrf_token": csrf, "password": "museum_default"})
    if "Admin Dashboard" in r.text or r.url.endswith("/admin"):
        print("Login successful! Session cookie obtained.")
    else:
        print("Login failed.")
except Exception as e:
    print("Error during login:", e)

# Save cookies
import pickle
with open("test_cookies", "wb") as f:
    pickle.dump(s.cookies, f)


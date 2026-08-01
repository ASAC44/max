import json
import urllib.request


def get_current_location():
    """
    Fetches the current location (latitude, longitude) using ip-api.com.
    Returns a dictionary with 'latitude' and 'longitude' keys, or None if failed.
    """
    try:
        # Use a timeout of 3 seconds to avoid hanging
        with urllib.request.urlopen("http://ip-api.com/json/", timeout=3) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "success":
                return {"latitude": data.get("lat"), "longitude": data.get("lon")}
    except Exception as e:
        print(f"Error fetching location from IP API: {e}")
    return None

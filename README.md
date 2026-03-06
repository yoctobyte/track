# Museum Kiosk Control

Museum Kiosk Control is a lightweight, secure web application designed to monitor and manage museum display kiosks connected via Tailscale. It provides a centralized dashboard to track device status, currently playing media, and allows administrative proxy access to individual kiosk web interfaces.

## Features

- **Tailscale Integration**: Automatically discovers and monitors devices connected to the Tailscale network.
- **Real-time Status**: Scrapes and displays active video, playback modes, and schedules from kiosk players.
- **Secure Admin Dashboard**: Add, configure, and manage device metadata (room, placement, notes) from a central location.
- **Device Proxy**: Access individual device web interfaces securely through the centralized proxy, protected by authentication.
- **Security-First Design**: Includes robust protections against brute-force attacks (IP and global rate limiting), CSRF protection, secure password hashing, and SSRF path sanitization.

## Getting Started

### Prerequisites

- Python 3.8+
- Tailscale installed and active on the host machine.
- Tailscale devices acting as kiosks (e.g., hostnames starting with `fons-`).

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/museumcontrol.git
   cd museumcontrol
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration

Before running the application, you must set an administration password.

1. Generate a secure admin password hash:
   ```bash
   python create_password.py
   ```
   *Follow the prompts to enter and confirm your secure password.*

2. (Optional) Customize the configuration by creating or editing `config.json` in the root directory:
   ```json
   {
     "title": "My Museum Kiosk Control",
     "port": 4575,
     "bind": "0.0.0.0"
   }
   ```

3. (Required for Production) Set a secure secret key via environment variable:
   ```bash
   export SECRET_KEY="your-super-strong-random-secret-key"
   ```

### Running the Application

You can use the provided bash script to run the application using `gunicorn` (recommended for production):

```bash
./run.sh
```

Alternatively, for development or a lightweight server setup, you can run the built-in Flask server:

```bash
python run.py
```

*Note: The application stores data in `app/data/`. Ensure proper permissions are set.*

## Security

This application has undergone a security review to ensure safe operation.
- **Passwords**: Hashed securely using Werkzeug (pbkdf2/scrypt).
- **Brute Force Protection**: Failed logins are rate-limited per IP (3 attempts/2 mins) and globally (20 attempts/1 min).
- **CSRF**: All form submissions are protected via Flask-WTF tokens.
- **Proxy**: The internal proxy safely sanitizes URLs to prevent directory traversal. Ensure you only proxy trusted internal network destinations.

## License

[MIT License](LICENSE)

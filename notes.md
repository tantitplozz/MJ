# Notes

* Run

```bash
bash setup.sh
source .venv/bin/activate
python run.py
```

* If Booking.com shows anti-bot or additional steps, re-run after manual completion. Adjust labels in `run.py` as needed.
* To use MoreLogin profiles, start the profile via its API and proxy Playwright traffic through that profile. Then add `playwright_custom_user_agent` or a proxy at OS level before running.
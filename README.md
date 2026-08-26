# PWF Auth Python Desktop Sample

An English Tkinter desktop client for the official `pwfauth` Python package.

## Configure

Set your 64-character application secret near the top of `app.py`:

```python
APP_SECRET = "YOUR_64_CHARACTER_APP_SECRET"
```

This is intentionally kept in the same file for the educational sample. For a
production application, prefer the `PWFAUTH_SECRET` environment variable so the
secret is not committed to source control.

## Run

Double-click `run.bat`, or run:

```powershell
.\.venv\Scripts\python.exe app.py
```

The application performs network work outside the Tkinter thread, opens a live
licensed session, starts the server-enforced heartbeat, displays every value from
the login response, and closes the server session when the user signs out.


# COSGC Digital Twin Dashboard

Open MCT-based dashboard for visualizing environmental and biometric sensor telemetry.

## Running the Dashboard

**Prerequisites:** Node.js and npm installed (Node.js 20.19+ or 22.12+ for Vite 8).

From the root of the capstone repository, run:

```bash
# Navigate to dashboard
cd src/dashboard

# Install dependencies
npm ci

# Set up Open MCT assets
mkdir -p public/openmct-assets
cp -R node_modules/openmct/dist/. public/openmct-assets/

# Start development server
npm run dev
```

Open the URL displayed in the terminal, typically:

**http://localhost:5173/**

The dashboard automatically reloads when source files are modified.

To stop the server, press `Ctrl+C`.

## Notes

- `npm ci` installs dependencies from `package-lock.json`.
- Open MCT assets must be copied after a fresh installation or dependency update.
- The dashboard currently uses hardcoded sensor values and is not yet connected to the Python data generator.
- Do not commit `node_modules/`, `dist/`, or generated Open MCT assets.
